import math
import unittest

from app.geo import bearing_deg, distance_m, is_valid_position


class Distances(unittest.TestCase):
    def test_one_degree_of_latitude_is_about_111_km(self):
        self.assertAlmostEqual(distance_m(0, 0, 1, 0), 111_195, delta=100)

    def test_the_same_point_is_zero_away(self):
        self.assertEqual(distance_m(40.7, -74.0, 40.7, -74.0), 0)

    def test_a_short_walk(self):
        self.assertAlmostEqual(distance_m(40.0, -74.0, 40.001, -74.0), 111.2, delta=1)


class Directions(unittest.TestCase):
    def test_compass_directions(self):
        self.assertAlmostEqual(bearing_deg(40, -74, 41, -74), 0, delta=0.5)
        self.assertAlmostEqual(bearing_deg(0, 0, 0, 1), 90, delta=0.5)
        self.assertAlmostEqual(bearing_deg(41, -74, 40, -74), 180, delta=0.5)
        self.assertAlmostEqual(bearing_deg(0, 1, 0, 0), 270, delta=0.5)


class Validation(unittest.TestCase):
    def test_real_positions_pass(self):
        self.assertTrue(is_valid_position(40.7, -74.0))
        self.assertTrue(is_valid_position(-90, 180))
        self.assertTrue(is_valid_position(0, 0))

    def test_nonsense_is_refused(self):
        for lat, lon in [(91, 0), (0, 181), (math.nan, 0), (0, math.inf), ("40", "-74"), (None, 1), (True, False)]:
            self.assertFalse(is_valid_position(lat, lon), (lat, lon))


if __name__ == "__main__":
    unittest.main()
