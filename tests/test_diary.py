import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from diary import ask, completion, logs, projects, store
from diary.todos import Todo, TodoList


class DiaryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("DIARY_DIR")
        os.environ["DIARY_DIR"] = self._tmp.name
        self.root = Path(self._tmp.name)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("DIARY_DIR", None)
        else:
            os.environ["DIARY_DIR"] = self._old
        self._tmp.cleanup()


class TodoTests(DiaryTestCase):
    def test_parse_roundtrip(self):
        line = "- [ ] (#3) Fix token refresh +api !p1 due:2026-11-01 created:2026-10-29"
        t = Todo.parse(line)
        self.assertEqual((t.id, t.text, t.project, t.priority), (3, "Fix token refresh", "api", 1))
        self.assertEqual(t.due, date(2026, 11, 1))
        self.assertEqual(t.render(), line)

    def test_hand_added_lines_get_ids_and_c_plus_plus_is_not_a_project(self):
        store.todos_path().write_text("- [ ] (#5) existing\n- [ ] learn C++ +lang\n* [x] old thing\n")
        tl = TodoList()
        self.assertEqual(sorted(t.id for t in tl.items), [5, 6, 7])
        self.assertEqual(tl.get(6).text, "learn C++")
        self.assertEqual(tl.get(6).project, "lang")
        self.assertTrue(tl.get(7).is_done)
        tl.save()
        self.assertEqual(len(TodoList().items), 3)

    def test_add_query_sort(self):
        tl = TodoList()
        tl.add("low", project="api", priority=3)
        tl.add("high", project="API", priority=1)
        tl.add("untagged")
        tl.save()
        tl = TodoList()
        self.assertEqual([t.text for t in tl.query(project="api")], ["high", "low"])
        self.assertEqual(len(tl.query()), 3)
        tl.get(1).done = date(2026, 10, 29)
        self.assertEqual([t.text for t in tl.query(include_open=False, include_done=True)], ["low"])


class LogTests(DiaryTestCase):
    def test_append_creates_sections_per_project(self):
        log = logs.DayLog(date(2026, 10, 29))
        log.append("fixed bug", project="api", when=datetime(2026, 10, 29, 10, 14))
        log.append("scaffolded cli", project="diary", when=datetime(2026, 10, 29, 13, 2))
        log.append("reviewed PR", project="API", when=datetime(2026, 10, 29, 15, 40))
        log.append("random thought", when=datetime(2026, 10, 29, 16, 0))
        sections = log.project_sections()
        self.assertEqual(sections["api"], "- 10:14 fixed bug\n- 15:40 reviewed PR")
        self.assertEqual(sections["diary"], "- 13:02 scaffolded cli")
        self.assertNotIn("notes", sections)
        self.assertIn("- 16:00 random thought", log.read())

    def test_open_todos_section_is_refreshed_and_ignored(self):
        tl = TodoList()
        tl.add("ship it", project="api")
        log = logs.DayLog(date(2026, 10, 29))
        log.refresh_open_todos(tl.query())
        log.refresh_open_todos(tl.query())
        text = log.read()
        self.assertEqual(text.count("## Open todos"), 1)
        self.assertIn("(#1) ship it +api", text)
        self.assertEqual(log.project_sections(), {})
        self.assertNotIn("ship it", log.for_context())

    def test_empty_project_heading_does_not_count(self):
        log = logs.DayLog(date(2026, 10, 29))
        log.path.write_text("# day\n\n## api\n\n<!-- nothing yet -->\n\n## web\nbuilt page\n")
        self.assertEqual(list(log.project_sections()), ["web"])


class ProjectsAndAskTests(DiaryTestCase):
    def test_collect_and_prompt(self):
        logs.DayLog(date(2026, 10, 1)).append("start", project="api")
        logs.DayLog(date(2026, 10, 5)).append("more", project="api")
        logs.DayLog(date(2026, 10, 5)).append("other", project="web")
        tl = TodoList()
        tl.add("todo", project="api")
        tl.save()

        hist = projects.collect()
        self.assertEqual(len(hist["api"].days), 2)
        self.assertEqual(hist["api"].first, date(2026, 10, 1))
        self.assertEqual(hist["api"].open_todos, 1)
        self.assertEqual(len(projects.collect(since=date(2026, 10, 2))["api"].days), 1)

        prompt = ask.build_prompt("what did I do?", project="web", today=date(2026, 10, 29))
        self.assertIn('<log date="2026-10-05">', prompt)
        self.assertNotIn('<log date="2026-10-01">', prompt)
        self.assertNotIn("more", prompt)
        self.assertIn("<todos>", prompt)


class ProjectStatusTests(DiaryTestCase):
    def test_add_close_reopen(self):
        logs.DayLog(date(2026, 10, 1)).append("start", project="api")
        projects.set_status("web", None)  # added before any use
        self.assertEqual(projects.known_names("open"), ["api", "web"])

        projects.set_status("api", date(2026, 10, 30))
        self.assertEqual(projects.known_names("open"), ["web"])
        self.assertEqual(projects.known_names("closed"), ["api"])
        self.assertEqual(projects.collect()["api"].closed, date(2026, 10, 30))
        self.assertEqual(len(projects.collect()["api"].days), 1)  # history kept
        self.assertIn("is closed", projects.new_project_warning("api"))

        projects.set_status("api", None)
        self.assertEqual(projects.known_names("open"), ["api", "web"])

    def test_hand_edited_registry(self):
        store.projects_path().write_text("## Open\n- api\n\n## Closed\n- old\n- older (closed 2026-01-02)\n")
        reg = projects.Registry()
        self.assertEqual(reg.entries, {"api": None, "old": date.min, "older": date(2026, 1, 2)})
        reg.save()
        self.assertEqual(projects.Registry().entries, reg.entries)

    def test_log_gets_sections_for_open_projects_only(self):
        projects.set_status("api", None)
        projects.set_status("web", None)
        projects.set_status("old", date(2026, 10, 1))
        log = logs.DayLog(date(2026, 10, 29))
        log.append("note", project="web")
        log.ensure_sections(projects.known_names("open"))
        log.ensure_sections(projects.known_names("open"))  # idempotent
        text = log.read()
        self.assertEqual((text.count("## api"), text.count("## web"), text.count("## old")), (1, 1, 0))
        self.assertEqual(list(log.project_sections()), ["web"])  # empty api heading isn't counted


class CompletionTests(DiaryTestCase):
    def test_complete_projects_and_todos(self):
        logs.DayLog(date(2026, 10, 1)).append("start", project="api")
        tl = TodoList()
        tl.add("open one", project="web")
        tl.add("finished: yes").done = date(2026, 10, 2)
        tl.save()
        self.assertEqual(completion.complete("projects"), ["api", "web"])
        self.assertEqual(completion.complete("todos-open"), ["1:open one +web"])
        self.assertEqual(completion.complete("todos-done"), ["2:finished: yes"])
        self.assertEqual(len(completion.complete("todos-all")), 2)

    def test_new_project_warning(self):
        logs.DayLog(date(2026, 10, 1)).append("start", project="api")
        self.assertIsNone(projects.new_project_warning("API"))
        self.assertIsNone(projects.new_project_warning(None))
        self.assertIn("did you mean +api", projects.new_project_warning("apo"))
        self.assertEqual(projects.new_project_warning("zzz"), "note: new project +zzz")


class DateTests(unittest.TestCase):
    def test_parse_day(self):
        today = date(2026, 10, 29)
        self.assertEqual(store.parse_day("yesterday", today), date(2026, 10, 28))
        self.assertEqual(store.parse_day("2w", today), date(2026, 10, 15))
        self.assertEqual(store.parse_day("2026-01-02", today), date(2026, 1, 2))
        with self.assertRaises(ValueError):
            store.parse_day("someday", today)


if __name__ == "__main__":
    unittest.main()
