import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from schema import create_schema
from serve import make_handler, read_tasks


class TaskDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "example"
        (self.project / "tasks").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_parses_statuses_and_ignores_examples(self):
        (self.project / "tasks" / "README.md").write_text("- [ ] convention example\n")
        (self.project / "tasks" / "work.md").write_text(
            "# Work\n- [ ] Start\n## Delivery\n- [~] Build\n"
            "      and verify the result.\n      - separate note\n"
            "- [!] Waiting\n- [x] Finished\n```md\n- [ ] example\n```\n"
        )
        result = read_tasks(self.project)
        self.assertEqual(result["counts"], {"todo": 1, "in_progress": 1, "blocked": 1, "done": 1})
        self.assertEqual(result["tasks"][1]["section"], "Delivery")
        self.assertEqual(result["tasks"][1]["line"], 4)
        self.assertEqual(result["tasks"][1]["title"], "Build and verify the result.")

    def test_api_reflects_edits_additions_and_deletions(self):
        source = self.project / "tasks" / "work.md"
        source.write_text("- [ ] First\n")
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.project))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def fetch():
                with urlopen(f"http://127.0.0.1:{server.server_port}/api/tasks") as response:
                    return json.load(response)

            first = fetch()
            source.write_text("- [x] First\n")
            edited = fetch()
            self.assertEqual(edited["counts"]["done"], 1)
            self.assertNotEqual(first["version"], edited["version"])
            source.unlink()
            (self.project / "tasks" / "new.md").write_text("- [~] New\n")
            latest = fetch()
            self.assertEqual([task["title"] for task in latest["tasks"]], ["New"])
            self.assertEqual(latest["counts"]["in_progress"], 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_priority_and_tag_come_from_the_schema(self):
        (self.project / "tasks" / "work.md").write_text(
            "- [ ] **P1 — Title the work.**\n      Also mvp.\n"
            "- [x] Crash recovery (mvp P0)\n"
            "- [ ] Plain item\n"
        )
        (self.project / "tasks" / "archive").mkdir()
        (self.project / "tasks" / "archive" / "old.md").write_text("- [x] Stored away\n")
        unschemad = read_tasks(self.project)["tasks"]
        self.assertTrue(all(task["priority"] is None and task["tag"] == [] for task in unschemad))
        create_schema(self.project, ["P0", "P1"], ["mvp"])
        tasks = {task["line"]: task for task in read_tasks(self.project)["tasks"]}
        self.assertEqual(tasks[1]["priority"], "P1")
        self.assertEqual(tasks[1]["tag"], ["mvp"])
        self.assertEqual(tasks[3]["priority"], "P0")
        self.assertEqual(tasks[3]["tag"], ["mvp"])
        self.assertIsNone(tasks[4]["priority"])
        self.assertEqual(tasks[4]["tag"], [])
        with self.assertRaises(FileExistsError):
            create_schema(self.project, ["P0"], ["mvp"])

    def test_archive_moves_only_a_finished_file_out_of_the_current_list(self):
        done = self.project / "tasks" / "done.md"
        open_file = self.project / "tasks" / "open.md"
        done.write_text("- [x] Finished\n")
        open_file.write_text("- [ ] Still open\n")
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.project))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def post(payload):
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/api/archive",
                    data=json.dumps(payload).encode(),
                    method="POST",
                )
                with urlopen(request) as response:
                    return response.status, json.load(response)

            with self.assertRaises(Exception) as rejected:
                post({"file": "tasks/open.md"})
            self.assertEqual(rejected.exception.code, 400)
            self.assertTrue(open_file.exists())

            status, archived = post({"file": "tasks/done.md"})
            self.assertEqual(status, 200)
            self.assertEqual([task["title"] for task in archived["tasks"]], ["Still open"])
            self.assertFalse(done.exists())
            self.assertEqual((self.project / "tasks" / "archive" / "done.md").read_text(), "- [x] Finished\n")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
