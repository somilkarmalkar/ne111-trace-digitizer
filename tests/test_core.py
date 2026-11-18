"""Meaningful numerical, export and input-format checks for the digitizer."""

import csv
import io
import math
import unittest

from PIL import Image
from app import Calibration, csv_export, frame_count, load_image


class CalibrationTests(unittest.TestCase):
    def assertPointAlmostEqual(self, actual, expected):
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, delta=max(abs(b) * 1e-11, 1e-9))

    def test_axis_aligned_screen_y_inversion(self):
        cal = Calibration((100, 500), (700, 500), (100, 100), 0, 12, -5, 15)
        self.assertPointAlmostEqual(cal.pixel_to_data(400, 300), (6, 5))
        self.assertPointAlmostEqual(cal.data_to_pixel(6, 5), (400, 300))

    def test_rotated_and_skewed_affine(self):
        for angle in (0, 0.12, -0.31, 1.3, 2.8):
            origin = (425, 372)
            vx = (640 * math.cos(angle), 640 * math.sin(angle))
            vy = (420 * math.cos(angle - 1.4), 420 * math.sin(angle - 1.4))
            cal = Calibration(origin, (origin[0] + vx[0], origin[1] + vx[1]),
                              (origin[0] + vy[0], origin[1] + vy[1]),
                              -4, 16, 30, -10)
            for u, v in ((0, 0), (1, 0), (0, 1), (.25, .7), (-.1, 1.2)):
                pixel = (origin[0] + u * vx[0] + v * vy[0],
                         origin[1] + u * vx[1] + v * vy[1])
                expected = (-4 + u * 20, 30 - v * 40)
                self.assertPointAlmostEqual(cal.pixel_to_data(*pixel), expected)
                self.assertPointAlmostEqual(cal.data_to_pixel(*expected), pixel)

    def test_semilog_and_loglog(self):
        for x_log, y_log in ((True, False), (False, True), (True, True)):
            cal = Calibration((0, 100), (200, 100), (0, 0),
                              1, 100, 10, 1000, x_log, y_log)
            expected = (10 if x_log else 50.5, 100 if y_log else 505)
            self.assertPointAlmostEqual(cal.pixel_to_data(100, 50), expected)
            self.assertPointAlmostEqual(cal.data_to_pixel(*expected), (100, 50))

    def test_reversed_log_axis(self):
        cal = Calibration((0, 0), (100, 0), (0, 100), 100, 1, 1000, 10, True, True)
        self.assertPointAlmostEqual(cal.pixel_to_data(50, 50), (10, 100))

    def test_invalid_reference_geometry_and_values(self):
        bad = [((0, 0), (0, 0), (0, 100), 0, 1, 0, 1),
               ((0, 0), (100, 0), (200, 0), 0, 1, 0, 1),
               ((0, 0), (100000, 0), (200000, .001), 0, 1, 0, 1),
               ((0, 0), (100, 0), (0, 100), 1, 1, 0, 1),
               ((0, 0), (100, 0), (0, 100), 0, float('inf'), 0, 1),
               ((float('nan'), 0), (100, 0), (0, 100), 0, 1, 0, 1)]
        for values in bad:
            with self.subTest(values=values), self.assertRaises(ValueError):
                Calibration(*values)
        with self.assertRaises(ValueError):
            Calibration((0, 0), (100, 0), (0, 100), 0, 100, 1, 10, True)

    def test_invalid_edited_log_point(self):
        cal = Calibration((0, 0), (100, 0), (0, 100), 1, 100, 1, 100, True, True)
        for x, y in ((0, 1), (1, -4), (float('nan'), 2)):
            with self.assertRaises(ValueError):
                cal.data_to_pixel(x, y)

    def test_log_overflow_and_underflow_are_errors(self):
        cal = Calibration((0, 0), (100, 0), (0, 100), 1, 100, 1, 100, True, True)
        for p in (20000, -20000):
            with self.assertRaises(ValueError):
                cal.pixel_to_data(p, 20)


class CsvTests(unittest.TestCase):
    def test_headers_unequal_lengths_quoting_and_precision(self):
        datasets = [
            {'name': 'Series, "A" α', 'values': [(1 / 3, -2), (4, 5)]},
            {'name': 'Line\nB', 'values': [(1e-100, 1e100)]},
            {'name': 'Empty', 'values': []},
        ]
        rows = list(csv.reader(io.StringIO(csv_export(datasets, 'Time, s', 'Force (N)'))))
        self.assertEqual(rows[0], ['Series, "A" α', '', 'Line\nB', '', 'Empty', ''])
        self.assertEqual(rows[1], ['Time, s', 'Force (N)'] * 3)
        self.assertEqual(rows[3], ['4.0', '5.0', '', '', '', ''])
        self.assertEqual(float(rows[2][0]), 1 / 3)
        self.assertEqual(float(rows[2][2]), 1e-100)
        self.assertTrue(all(len(row) == 6 for row in rows))

    def test_empty_series_preserves_headers(self):
        rows = list(csv.reader(io.StringIO(csv_export([{'name': 'A', 'values': []}]))))
        self.assertEqual(rows, [['A', ''], ['x', 'y']])


class ImageTests(unittest.TestCase):
    def encode(self, image, fmt, **kwargs):
        data = io.BytesIO()
        image.save(data, format=fmt, **kwargs)
        return data.getvalue()

    def test_common_formats_grayscale_and_color(self):
        for fmt in ('PNG', 'JPEG', 'GIF', 'TIFF'):
            for mode in ('L', 'RGB'):
                with self.subTest(fmt=fmt, mode=mode):
                    original = Image.new(mode, (32, 24), 80 if mode == 'L' else '#5280af')
                    loaded = load_image(self.encode(original, fmt))
                    self.assertEqual(loaded.size, original.size)
                    self.assertEqual(loaded.mode, 'RGB')

    def test_transparency_composites_white(self):
        loaded = load_image(self.encode(Image.new('RGBA', (20, 20), (0, 0, 0, 0)), 'PNG'))
        self.assertEqual(loaded.getpixel((0, 0)), (255, 255, 255))

    def test_high_bit_depth_grayscale_retains_contrast(self):
        for fmt in ('PNG', 'TIFF'):
            original = Image.new('I;16', (3, 1))
            for x, value in enumerate((0, 32768, 65535)):
                original.putpixel((x, 0), value)
            loaded = load_image(self.encode(original, fmt))
            self.assertEqual(loaded.getpixel((0, 0)), (0, 0, 0))
            self.assertIn(loaded.getpixel((1, 0))[0], (127, 128))
            self.assertEqual(loaded.getpixel((2, 0)), (255, 255, 255))

    def test_animated_frames_and_multipage_tiff(self):
        for fmt in ('GIF', 'TIFF'):
            a = Image.new('RGB', (20, 20), 'red')
            b = Image.new('RGB', (20, 20), 'blue')
            data = self.encode(a, fmt, save_all=True, append_images=[b])
            self.assertEqual(frame_count(data), 2)
            self.assertEqual(load_image(data, 0).getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(load_image(data, 1).getpixel((0, 0)), (0, 0, 255))
            with self.assertRaises(ValueError):
                load_image(data, 2)

    def test_exif_orientation(self):
        original = Image.new('RGB', (20, 10), 'red')
        exif = Image.Exif()
        exif[274] = 6
        data = self.encode(original, 'JPEG', exif=exif)
        self.assertEqual(load_image(data).size, (10, 20))

    def test_corrupt_file_rejected(self):
        with self.assertRaises(ValueError):
            load_image(b'This is not an image')


if __name__ == '__main__':
    unittest.main(verbosity=2)
