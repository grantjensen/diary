import os
import tempfile
import contextlib
import io
import unittest
from unittest import mock
from datetime import date, datetime
from pathlib import Path

from diary import ask, completion, logs, projects, prs, store
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


class DeprecatedTodoTests(DiaryTestCase):
    def test_deprecated_roundtrip_and_queries(self):
        tl = TodoList()
        tl.add("keep", project="api")
        tl.add("drop", project="api").deprecated = date(2026, 11, 3)
        tl.add("finished", project="api").done = date(2026, 11, 2)
        tl.save()
        text = store.todos_path().read_text()
        self.assertIn("## Deprecated\n\n- [-] (#2) drop +api", text)
        self.assertIn("deprecated:2026-11-03", text)

        tl = TodoList()
        self.assertTrue(tl.get(2).is_deprecated)
        self.assertFalse(tl.get(2).is_open)
        self.assertEqual([t.text for t in tl.query()], ["keep"])
        self.assertEqual([t.text for t in tl.query(include_open=False, include_deprecated=True)], ["drop"])
        self.assertEqual(len(tl.query(include_done=True, include_deprecated=True)), 3)

        hist = projects.collect()["api"]
        self.assertEqual((hist.open_todos, hist.done_todos), (1, 1))  # deprecated counts as neither

    def test_hand_written_dash_box_is_deprecated(self):
        store.todos_path().write_text("- [-] (#1) old idea\n")
        t = TodoList().get(1)
        self.assertTrue(t.is_deprecated)
        self.assertEqual(t.render(), "- [-] (#1) old idea")


class TodoAddPromptTests(DiaryTestCase):
    def run_add(self, answers, argv=("todo", "add")):
        from diary import cli
        with mock.patch("builtins.input", side_effect=list(answers)), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(list(argv))
        return TodoList().items[-1]

    def test_prompts_for_each_field(self):
        projects.set_status("api", None)
        t = self.run_add(["Fix a -> b | c", "api", "7", "2", "nope", "2026-12-01"])
        self.assertEqual((t.text, t.project, t.priority, t.due), ("Fix a -> b | c", "api", 2, date(2026, 12, 1)))

    def test_enter_skips_and_new_project_needs_confirmation(self):
        projects.set_status("api", None)
        t = self.run_add(["thing", "apo", "", "", "", ""])  # typo declined, then project skipped
        self.assertEqual((t.project, t.priority, t.due), (None, None, None))
        t = self.run_add(["other", "web", "y", "", ""])
        self.assertEqual(t.project, "web")

    def test_flags_skip_their_prompts(self):
        t = self.run_add(["flagged", ""], argv=("todo", "add", "-p", "api", "--pri", "1"))  # only text + due asked
        self.assertEqual((t.project, t.priority, t.due), ("api", 1, None))


class TodoEditPromptTests(DiaryTestCase):
    run_add = TodoAddPromptTests.run_add

    def edit(self, answers, todo_id=1):
        from diary import cli
        with mock.patch("builtins.input", side_effect=list(answers)), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["todo", "edit", str(todo_id)])
        return TodoList().get(todo_id)

    def test_enter_keeps_dash_clears(self):
        projects.set_status("api", None)
        self.run_add(["original", "api", "2", "2026-12-01"])
        t = self.edit(["", "-", "1", ""])  # keep text, clear project, p1, keep due
        self.assertEqual((t.text, t.project, t.priority, t.due), ("original", None, 1, date(2026, 12, 1)))
        t = self.edit(["new text -> here", "", "-", "-"])
        self.assertEqual((t.text, t.project, t.priority, t.due), ("new text -> here", None, None, None))


class ClosedProjectReopenTests(DiaryTestCase):
    run_add = TodoAddPromptTests.run_add

    def test_open_todo_reopens_closed_project(self):
        from diary import cli
        projects.set_status("api", None)
        t = self.run_add(["task", "api", "", ""])
        with self.assertRaises(SystemExit):  # can't close with an open todo
            cli.main(["projects", "close", "api"])
        self.assertEqual(projects.known_names("closed"), [])

        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["todo", "done", str(t.id)])
            cli.main(["projects", "close", "api"])
        self.assertEqual(projects.known_names("closed"), ["api"])

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["todo", "undo", str(t.id)])  # reopening the todo reopens the project
        self.assertEqual(projects.known_names("closed"), [])

        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["todo", "done", str(t.id)])
            cli.main(["projects", "close", "api"])
        self.run_add(["another", "api", "", ""])  # adding to a closed project reopens it too
        self.assertEqual(projects.known_names("open"), ["api"])


class PRSyncTests(DiaryTestCase):
    @staticmethod
    def pr(n, merged):
        return prs.MergedPR("togethercomputer/tiny-engine", n, f"title {n}",
                            f"https://github.com/togethercomputer/tiny-engine/pull/{n}", merged)

    def test_logs_under_merge_day_once_per_day_and_never_twice(self):
        logs.DayLog(date(2026, 11, 1)).append("first day", project="api")  # diary starts Nov 1
        available = [self.pr(1, datetime(2026, 11, 2, 9, 30)), self.pr(2, datetime(2026, 11, 4, 16, 20))]
        asked = []

        def fetch(since):
            asked.append(since)
            return [p for p in available if p.merged.date() >= since]

        new = prs.sync(today=date(2026, 11, 4), fetch=fetch)
        self.assertEqual([p.number for p in new], [1, 2])
        self.assertEqual(asked, [date(2026, 11, 1)])  # first sync goes back to the first diary day
        day = logs.DayLog(date(2026, 11, 2)).read()
        self.assertIn("## PRs\n\n- 09:30 merged tiny-engine#1: title 1\n  https://github.com/", day)
        self.assertIn("16:20 merged tiny-engine#2", logs.DayLog(date(2026, 11, 4)).read())
        self.assertNotIn("prs", logs.DayLog(date(2026, 11, 2)).project_sections())  # not a project

        self.assertIsNone(prs.sync(today=date(2026, 11, 4), fetch=fetch))  # already synced today
        available.append(self.pr(3, datetime(2026, 11, 5, 11, 0)))
        new = prs.sync(today=date(2026, 11, 6), fetch=fetch)  # skipped Nov 5: caught up
        self.assertEqual([p.number for p in new], [3])
        self.assertEqual(asked[-1], date(2026, 11, 4))  # from the last sync day; overlap is deduped
        self.assertEqual(logs.DayLog(date(2026, 11, 4)).read().count("tiny-engine#2"), 1)
        self.assertEqual(prs.sync(today=date(2026, 11, 6), force=True, fetch=fetch), [])

    def test_gh_failure_is_retried(self):
        def broken(since):
            raise RuntimeError("offline")

        with self.assertRaises(RuntimeError):
            prs.sync(today=date(2026, 11, 4), fetch=broken)
        self.assertIsNotNone(prs.sync(today=date(2026, 11, 4), fetch=lambda since: []))  # not marked synced


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

    def test_parse_day_future_for_due_dates(self):
        thu = date(2026, 10, 29)  # a Thursday
        self.assertEqual(store.parse_day("3d", thu, future=True), date(2026, 11, 1))
        self.assertEqual(store.parse_day("2w", thu, future=True), date(2026, 11, 12))
        self.assertEqual(store.parse_day("-3d", thu, future=True), date(2026, 10, 26))
        self.assertEqual(store.parse_day("+3d", thu), date(2026, 11, 1))
        self.assertEqual(store.parse_day("fri", thu, future=True), date(2026, 10, 30))
        self.assertEqual(store.parse_day("thu", thu, future=True), date(2026, 11, 5))  # next week, not today
        self.assertEqual(store.parse_day("Monday", thu, future=True), date(2026, 11, 2))

    def test_parse_day_weekdays_look_back_by_default(self):
        thu = date(2026, 10, 29)
        self.assertEqual(store.parse_day("mon", thu), date(2026, 10, 26))
        self.assertEqual(store.parse_day("thu", thu), thu)  # today counts
        self.assertEqual(store.parse_day("fri", thu), date(2026, 10, 23))
        with self.assertRaises(ValueError):
            store.parse_day("fr", thu)  # too short to be unambiguous


if __name__ == "__main__":
    unittest.main()
