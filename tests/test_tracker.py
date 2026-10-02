"""Tracker tests on synthetic moving boxes:  python -m unittest discover tests"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "relabel_gui_app"))
import trackers as tracker  # noqa: E402
import scenes  # noqa: E402  (tests/ is on sys.path under unittest discover)

# (true id, class, x0, y0, size, dx, dy)
OBJECTS = [("a", "car", 20, 60, 70, 12, 1), ("b", "person", 560, 220, 40, -9, -1),
           ("c", "car", 200, 250, 90, 5, -2), ("d", "bicycle", 320, 30, 50, -4, 3)]


def make_frames(n=40, seed=0, drop=0.0, jitter=0.0, weak_scores=False, flip=0.0, prefix="clip"):
    rnd = random.Random(seed)
    frames, truth = [], []
    for f in range(n):
        regs, gt = [], []
        for oid, cls, x0, y0, s, dx, dy in OBJECTS:
            if rnd.random() < drop:
                continue
            box = [x0 + dx * f + rnd.uniform(-jitter, jitter), y0 + dy * f + rnd.uniform(-jitter, jitter), s, s]
            c = cls if rnd.random() >= flip else "other"
            regs.append({"box": box, "score": rnd.uniform(0.2, 1.0) if weak_scores else None, "cls": c})
            gt.append((oid, cls))
        order = list(range(len(regs)))
        rnd.shuffle(order)
        frames.append({"file": f"{prefix}_frame_{f:06d}.jpg", "regions": [regs[i] for i in order]})
        truth.append([gt[i] for i in order])
    return frames, truth


def ids_per_object(res, truth):
    seen = {}
    for row_ids, row_gt in zip(res["ids"], truth):
        for tid, (oid, _) in zip(row_ids, row_gt):
            seen.setdefault(oid, set()).add(tid)
    return seen


class TrackerTest(unittest.TestCase):
    def test_clean_boxes_one_id_per_object(self):
        frames, truth = make_frames()
        res = tracker.run(frames)
        self.assertEqual(res["tracks"], 4)
        self.assertTrue(all(len(v) == 1 for v in ids_per_object(res, truth).values()))

    def test_every_box_gets_an_id(self):
        frames, _ = make_frames(drop=0.3, jitter=3, weak_scores=True, seed=4)
        res = tracker.run(frames)
        self.assertTrue(all(tid for row in res["ids"] for tid in row))

    def test_survives_jitter_weak_scores_and_missed_boxes(self):
        frames, truth = make_frames(drop=0.1, jitter=3, weak_scores=True)
        per = ids_per_object(tracker.run(frames), truth)
        self.assertTrue(all(len(v) == 1 for v in per.values()), per)

    def test_majority_vote_fixes_class_flicker(self):
        frames, truth = make_frames(flip=0.15)
        res = tracker.run(frames)
        true_cls = {oid: c for row in truth for oid, c in row}
        for oid, tids in ids_per_object(res, truth).items():
            for t in tids:
                self.assertEqual(res["classes"][t], true_cls[oid])

    def test_sequences_are_tracked_separately(self):
        f1, _ = make_frames(n=10, prefix="videoA")
        f2, _ = make_frames(n=10, prefix="videoB")
        res = tracker.run(f1 + f2)
        self.assertEqual(res["sequences"], 2)
        first = {t for row in res["ids"][:10] for t in row}
        second = {t for row in res["ids"][10:] for t in row}
        self.assertFalse(first & second)             # no id continues across videos

    def test_class_aware_never_links_different_classes(self):
        frames = [{"file": f"f_{i}.jpg", "regions": [{"box": [10 + i, 10, 50, 50], "score": 1.0,
                                                      "cls": "car" if i < 5 else "person"}]}
                  for i in range(10)]
        self.assertEqual(tracker.run(frames)["tracks"], 1)
        self.assertEqual(tracker.run(frames, class_aware=True)["tracks"], 2)


if __name__ == "__main__":
    unittest.main()



class MethodsTest(unittest.TestCase):
    def test_registry_lists_every_method_with_a_label(self):
        ids = [m["id"] for m in tracker.describe()]
        self.assertEqual(ids, ["bytetrack", "ocsort", "ocsort-rejoin"])
        self.assertTrue(all(m["label"] and m["description"] for m in tracker.describe()))
        with self.assertRaises(ValueError):
            tracker.run([], method="nope")

    def test_every_method_tracks_a_clean_scene_perfectly(self):
        frames, truth = scenes.make("smooth")
        for m in ("bytetrack", "ocsort", "ocsort-rejoin"):
            s = scenes.score(tracker.run(frames, method=m), truth)
            self.assertEqual((s["ids_per_object"], s["wrong_merges"]), (1.0, 0), m)

    def test_rejoin_bridges_an_occlusion_longer_than_the_track_buffer(self):
        frames, truth = scenes.make("long occlusion")
        online = scenes.score(tracker.run(frames, method="ocsort"), truth)
        rejoined = scenes.score(tracker.run(frames, method="ocsort-rejoin"), truth)
        self.assertGreater(online["ids_per_object"], 1.0)        # the online tracker gave up
        self.assertEqual((rejoined["ids_per_object"], rejoined["wrong_merges"]), (1.0, 0))

    def test_rejoin_never_links_across_videos(self):
        f1, _ = scenes.make("long occlusion", prefix="videoA")
        f2, _ = scenes.make("long occlusion", prefix="videoB")
        res = tracker.run(f1 + f2, method="ocsort-rejoin")
        n = len(f1)
        self.assertFalse({t for r in res["ids"][:n] for t in r} & {t for r in res["ids"][n:] for t in r})

    def test_ocsort_keeps_ids_through_sharp_turns_better_than_bytetrack(self):
        frames, truth = scenes.make("turns", drop=0.1, weak_scores=True)
        byte = scenes.score(tracker.run(frames, method="bytetrack"), truth)
        oc = scenes.score(tracker.run(frames, method="ocsort"), truth)
        self.assertLess(oc["ids_per_object"], byte["ids_per_object"])

    def test_people_crossing_keep_their_own_ids(self):
        frames, truth = scenes.make("crossing")
        for m in ("bytetrack", "ocsort", "ocsort-rejoin"):
            self.assertEqual(scenes.score(tracker.run(frames, method=m), truth)["wrong_merges"], 0, m)
