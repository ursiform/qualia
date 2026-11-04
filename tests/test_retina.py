"""Tests for egocentric Retina 1D-to-2D projection and optical flow."""

from __future__ import annotations

import unittest

from qualia import Retina, center_of_mass_x, extract_patches


class TestRetina(unittest.TestCase):
    def test_ego_turn_shifts_columns_appropriately(self) -> None:
        retina = Retina()
        f0 = retina.observe(distance=0.25, color=(250, 200, 80), turn="still")
        com_center = center_of_mass_x(f0)
        self.assertAlmostEqual(com_center, 31.5, delta=1.0)

        # Turning left shifts previously observed visual columns rightward (+x)
        f_left = retina.observe(distance=0.25, color=(250, 200, 80), turn="left")
        com_after_left = center_of_mass_x(f_left)
        self.assertGreater(com_after_left, com_center + 0.5)

        patches_0 = extract_patches(f0)
        patches_left = extract_patches(f_left, patches_0)
        total_drift_left = sum(p.drift for p in patches_left)
        rightward_dx = sum(p.dx for p in patches_left if p.x in (8, 9))
        self.assertGreater(total_drift_left, 0.0)
        self.assertGreater(rightward_dx, 0)

        # Reset and test right turn -> shifts visual columns leftward (-x)
        retina.reset()
        r0 = retina.observe(distance=0.25, color=(250, 200, 80), turn="still")
        r_right = retina.observe(distance=0.25, color=(250, 200, 80), turn="right")
        com_after_right = center_of_mass_x(r_right)
        self.assertLess(com_after_right, com_center - 0.5)

        patches_r0 = extract_patches(r0)
        patches_right = extract_patches(r_right, patches_r0)
        leftward_dx = sum(p.dx for p in patches_right if p.x in (6, 7))
        self.assertLess(leftward_dx, 0)

    def test_forward_approach_produces_looming_rise(self) -> None:
        retina = Retina()
        far = retina.observe(distance=0.85, color=(220, 240, 255), turn="still")
        mid = retina.observe(distance=0.45, color=(220, 240, 255), turn="forward")
        near = retina.observe(distance=0.10, color=(220, 240, 255), turn="forward")

        p_far = extract_patches(far)
        p_mid = extract_patches(mid, p_far)
        p_near = extract_patches(near, p_mid)

        power_far = sum(p.power for p in p_far) / len(p_far)
        power_mid = sum(p.power for p in p_mid) / len(p_mid)
        power_near = sum(p.power for p in p_near) / len(p_near)

        self.assertGreater(power_mid, power_far)
        self.assertGreater(power_near, power_mid)

        rise_mid = sum(p.rise for p in p_mid)
        rise_near = sum(p.rise for p in p_near)
        self.assertGreater(rise_mid, 0.0)
        self.assertGreater(rise_near, 0.0)

    def test_physical_cm_distance_and_patterns(self) -> None:
        retina = Retina(max_distance=100.0, units="physical")
        f_far = retina.observe(
            distance=80.0,
            color=(255, 120, 120),
            pattern="circle",
            cue="circle",
        )
        f_close = retina.observe(
            distance=15.0,
            color=(255, 120, 120),
            pattern="stripes",
            cue="stripes",
        )
        p_far = extract_patches(f_far)
        p_close = extract_patches(f_close, p_far)
        self.assertGreater(
            sum(p.power for p in p_close),
            sum(p.power for p in p_far),
        )
        self.assertEqual(f_far.cue, "circle")
        self.assertEqual(f_close.cue, "stripes")


if __name__ == "__main__":
    unittest.main()
