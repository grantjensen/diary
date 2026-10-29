import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from diary import ask, logs, projects, store
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
