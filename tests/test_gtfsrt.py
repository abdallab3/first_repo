import unittest

from app.gtfsrt import FeedError, parse_vehicle_positions
from tests import pbhelp as pb


class ReadingAFeed(unittest.TestCase):
    def test_reads_positions_routes_and_times(self):
        data = pb.feed(
            [
                pb.vehicle_entity("e1", route="12", lat=40.75, lon=-73.98, bearing=90.0, speed=6.5,
                                  vehicle_id="bus-7", label="7", timestamp=1_700_000_100, trip="t9"),
                pb.vehicle_entity("e2", route="B", lat=-33.86, lon=151.2),
            ],
            timestamp=1_700_000_120,
        )
        feed_time, vehicles = parse_vehicle_positions(data)
        self.assertEqual(feed_time, 1_700_000_120)
        self.assertEqual(len(vehicles), 2)
        first = vehicles[0]
        self.assertEqual((first["id"], first["label"], first["route"], first["trip"]), ("bus-7", "7", "12", "t9"))
        self.assertAlmostEqual(first["lat"], 40.75, places=4)
        self.assertAlmostEqual(first["lon"], -73.98, places=4)
        self.assertAlmostEqual(first["bearing"], 90.0, places=2)
        self.assertAlmostEqual(first["speed"], 6.5, places=2)
        self.assertEqual(first["timestamp"], 1_700_000_100)
        self.assertAlmostEqual(vehicles[1]["lat"], -33.86, places=3)  # southern and eastern hemispheres

    def test_a_vehicle_without_an_id_uses_the_entity_id(self):
        _, vehicles = parse_vehicle_positions(pb.feed([pb.vehicle_entity("entity-5", lat=1.0, lon=2.0)]))
        self.assertEqual(vehicles[0]["id"], "entity-5")

    def test_vehicles_without_a_usable_position_are_left_out(self):
        data = pb.feed(
            [
                pb.vehicle_entity("no-position", route="1"),
                pb.vehicle_entity("only-lat", lat=40.0),
                pb.vehicle_entity("null-island", lat=0.0, lon=0.0),
                pb.vehicle_entity("off-planet", lat=95.0, lon=10.0),
                pb.vehicle_entity("removed", lat=40.0, lon=-70.0, deleted=True),
                pb.vehicle_entity("good", lat=40.0, lon=-70.0),
            ]
        )
        _, vehicles = parse_vehicle_positions(data)
        self.assertEqual([v["id"] for v in vehicles], ["good"])

    def test_fields_this_app_does_not_use_are_skipped(self):
        extra = pb.string(15, "future field") + pb.uint(9, 3) + pb.flt(12, 1.5)
        _, vehicles = parse_vehicle_positions(pb.feed([pb.vehicle_entity("e", lat=1.0, lon=2.0, extra=extra)]))
        self.assertEqual(len(vehicles), 1)

    def test_an_empty_feed_with_a_header_is_fine(self):
        feed_time, vehicles = parse_vehicle_positions(pb.feed([], timestamp=5))
        self.assertEqual((feed_time, vehicles), (5, []))


class RefusingBadData(unittest.TestCase):
    def test_garbage_is_not_a_feed(self):
        for data in [b"", b"<html>not a feed</html>", b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"]:
            with self.assertRaises(FeedError, msg=data):
                parse_vehicle_positions(data)

    def test_a_cut_off_feed_is_refused(self):
        data = pb.feed([pb.vehicle_entity("e", route="12", lat=40.0, lon=-70.0)], timestamp=1)
        for cut in (len(data) - 1, len(data) - 5, 12):
            with self.assertRaises(FeedError, msg=cut):
                parse_vehicle_positions(data[:cut])

    def test_unknown_wire_types_are_refused(self):
        with self.assertRaises(FeedError):
            parse_vehicle_positions(pb.key(1, 3) + b"x")


if __name__ == "__main__":
    unittest.main()
