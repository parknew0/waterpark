from __future__ import annotations

import unittest

from routing import calculate_route


class FloodAwareRoutingTest(unittest.TestCase):
    def test_hinnamnor_route_avoids_current_flood_edges(self) -> None:
        route = calculate_route(
            {
                "scenario": "hinnamnor",
                "origin": {"latitude": 35.9835575, "longitude": 129.406536},
                "destination": {
                    "latitude": 35.98538485,
                    "longitude": 129.4007387,
                    "id": "safe-parking",
                    "name": "제철복지회관 임시주차장",
                    "address": "경상북도 포항시 남구 인덕동 47-4",
                },
            }
        )

        decision = route["routeDecision"]
        self.assertTrue(decision["avoidedCurrentFlood"])
        self.assertGreater(decision["baselineBlockedEdgeCount"], 0)
        self.assertEqual(decision["lowerRiskBlockedEdgeCount"], 0)
        self.assertGreater(route["distanceMeters"], route["baselineDistanceMeters"])
        self.assertEqual(route["riskZones"][0]["level"], "CURRENT")
        self.assertFalse(route["destination"]["safetyVerified"])


if __name__ == "__main__":
    unittest.main()
