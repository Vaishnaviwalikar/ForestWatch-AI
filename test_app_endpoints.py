import unittest
import json
from app import app

class TestAppEndpoints(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_index_route(self):
        response = self.app.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"ForestWatch AI", response.data)
        self.assertIn(b"ws-overview", response.data)
        self.assertIn(b"ws-explorer", response.data)
        self.assertIn(b"ws-vegetation", response.data)
        self.assertIn(b"ws-change", response.data)
        self.assertIn(b"ws-historical", response.data)
        self.assertIn(b"ws-reports", response.data)
        self.assertIn(b"ws-settings", response.data)

    def test_api_locations(self):
        response = self.app.get('/api/locations')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("locations", data)
        self.assertGreater(len(data["locations"]), 0)

    def test_api_geocode(self):
        response = self.app.get('/api/geocode?q=Western')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("results", data)
        self.assertGreater(len(data["results"]), 0)

    def test_analyses_list(self):
        response = self.app.get('/analyses')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("analyses", data)

    def test_status_endpoint(self):
        response = self.app.get('/status')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn("status", data)

if __name__ == '__main__':
    unittest.main()
