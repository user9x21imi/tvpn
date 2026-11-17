import math
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from globe import Camera,render,project,size,texture,wrap
from riseup_regions import REGIONS


class GlobeTests(unittest.TestCase):
    def test_selected_city_projects_to_center(self):
        for region in REGIONS.values():
            self.assertEqual(project(region['lat'],region['lon'],region['lat'],region['lon'],61,23),(30,11))

    def test_back_of_sphere_is_hidden(self):
        self.assertIsNone(project(0,180,0,0,60,22))
        self.assertIsNone(project(-45,180,45,0,60,22))

    def test_country_texture_tracks_real_countries(self):
        pixels,ids=texture()
        def at(lat,lon):return pixels[int((90-lat)/180*360)][int((lon+180)/360*720)]
        self.assertEqual(at(48.86,2.35),ids['FRA'])
        self.assertEqual(at(52.37,4.90),ids['NLD'])
        self.assertEqual(at(40,-100),ids['USA'])
        self.assertEqual(at(0,-130),0)

    def test_ascii_globe_and_selected_region_dots(self):
        rows=render(70,25,48,2,'FR',location=(48.86,2.35))
        self.assertEqual((len(rows),len(rows[0])),(25,70))
        self.assertTrue(all(cell.char.isascii() for row in rows for cell in row))
        self.assertTrue(any(cell.role==3 and cell.char=='.' for row in rows for cell in row))
        self.assertEqual(sum(cell.role==4 for row in rows for cell in row),1)
        self.assertTrue(any(cell.role==2 for row in rows for cell in row))
        self.assertEqual(rows[0][0].char,' ')

    def test_globe_respects_terminal_character_aspect_ratio(self):
        rx,ry=size(80,25)
        self.assertEqual(rx,ry*2)
        self.assertLessEqual(ry,12)

    def test_camera_smoothly_focuses_every_supported_region(self):
        camera=Camera();now=camera.last
        for key,region in REGIONS.items():
            camera.select(key,region['lat'],region['lon'])
            self.assertIsNotNone(camera.target)
            for _ in range(25):now+=.1;camera.tick(now)
            self.assertAlmostEqual(camera.latitude,region['lat'],delta=.03)
            self.assertAlmostEqual(wrap(camera.longitude-region['lon']),0,delta=.03)

    def test_dateline_uses_short_path_and_manual_pan_is_preserved(self):
        camera=Camera();camera.longitude=179;camera.focus(0,-179)
        camera.tick(camera.last+.1)
        self.assertLess(abs(wrap(camera.longitude-179)),2)
        camera.select('paris',48.86,2.35);camera.pan(5,12)
        expected=(camera.latitude,camera.longitude)
        camera.select('paris',48.86,2.35)
        self.assertIsNone(camera.target)
        self.assertEqual((camera.latitude,camera.longitude),expected)

    def test_spin_pause_and_zoom_bounds(self):
        camera=Camera();before=camera.longitude
        camera.toggle();camera.tick(camera.last+.1)
        self.assertNotEqual(camera.longitude,before)
        camera.toggle();before=camera.longitude;camera.tick(camera.last+.1)
        self.assertEqual(camera.longitude,before)
        camera.scale(100);self.assertEqual(camera.zoom,2.5)
        camera.scale(.0001);self.assertEqual(camera.zoom,.65)
        camera.pan(1000,0);self.assertLessEqual(camera.latitude,80)

    def test_mouse_region_bounds_are_explicit(self):
        camera=Camera();self.assertFalse(camera.contains(10,10))
        camera.box=(2,6,60,22)
        self.assertTrue(camera.contains(3,7));self.assertFalse(camera.contains(100,40))


if __name__=='__main__':unittest.main(verbosity=2)
