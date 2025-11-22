"""
Unit tests for gesture smoothing and deadzone logic.
"""

import unittest
from cv_controller import CVController

class GestureLogicTests(unittest.TestCase):
    def test_smooth_pos_initial(self):
        self.assertAlmostEqual(CVController.smooth_pos(None, 0.7), 0.7)

    def test_smooth_pos(self):
        out = CVController.smooth_pos(0.2, 0.8, alpha=0.5)
        self.assertAlmostEqual(out, 0.5)

    def test_deadzone_true(self):
        self.assertTrue(CVController.in_deadzone(0.5, 0.52, dz=0.05))

    def test_deadzone_false(self):
        self.assertFalse(CVController.in_deadzone(0.5, 0.6, dz=0.05))

if __name__ == "__main__":
    unittest.main()
