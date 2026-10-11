import asyncio
import math
import random
from datetime import datetime
from typing import Dict, List, Optional

from .provider import TransitDataProvider
from .eta_service import ETAService, haversine_distance_km
from .occupancy_service import OccupancyService
from .crowd_service import crowd_service
from .incident_service import incident_service
from ..models.transit import (
    Bus,
    BusLocation,
    BusStop,
    Route,
    Occupancy,
    ETAEstimate,
    Coordinate,
    AccessibilityMetadata,
    AccessibilityStatus,
    CrowdMetadata,
    Incident,
)


class MockTransitDataProvider(TransitDataProvider):
    """
    Simulated transit telemetry provider implementing TransitDataProvider.
    
    Generates realistic dynamic GPS coordinates along real Bengaluru road arterials,
    advances buses through sequence waypoints, modulates speed and direction,
    and updates passenger passenger counts.
    """

    def __init__(self):
        unknown_acc = AccessibilityMetadata(
            status=AccessibilityStatus.UNKNOWN,
            wheelchair_accessible=None,
            low_floor_bus=None,
            boarding_assistance_available=False,
            accessible_stop=False,
            audio_announcements=False,
            visual_displays=False,
            accessibility_disclosure="Accessibility information unavailable from the current transit data.",
            accessibility_source="simulated_corridor",
        )

        self._stops: Dict[str, BusStop] = {
            "stop-silk-board": BusStop(
                stop_id="stop-silk-board",
                name="Central Silk Board Junction",
                kannada_name="ಸಿಲ್ಕ್ ಬೋರ್ಡ್ ಜಂಕ್ಷನ್",
                latitude=12.9176,
                longitude=77.6238,
                accessibility=AccessibilityMetadata(
                    status=AccessibilityStatus.ACCESSIBLE,
                    wheelchair_accessible=True,
                    low_floor_bus=None,
                    boarding_assistance_available=True,
                    accessible_stop=True,
                    audio_announcements=True,
                    visual_displays=False,
                    accessibility_disclosure="Verified wheelchair accessible junction with ramp access.",
                    accessibility_source="bmtc_station_database",
                ),
            ),
            "stop-btm-water-tank": BusStop(
                stop_id="stop-btm-water-tank",
                name="BTM Layout Water Tank",
                kannada_name="ಬಿ.ಟಿ.ಎಂ ವಾಟರ್ ಟ್ಯಾಂಕ್",
                latitude=12.9152,
                longitude=77.6120,
                accessibility=unknown_acc,
            ),
            "stop-jayadeva": BusStop(
                stop_id="stop-jayadeva",
                name="Jayadeva Hospital",
                kannada_name="ಜಯದೇವ ಆಸ್ಪತ್ರೆ",
                latitude=12.9180,
                longitude=77.5980,
                accessibility=unknown_acc,
            ),
            "stop-majestic": BusStop(
                stop_id="stop-majestic",
                name="Majestic (Kempegowda Bus Station)",
                kannada_name="ಮೆಜೆಸ್ಟಿಕ್ ಕೆ.ಬಿ.ಎಸ್",
                latitude=12.9774,
                longitude=77.5708,
                accessibility=AccessibilityMetadata(
                    status=AccessibilityStatus.ACCESSIBLE,
                    wheelchair_accessible=True,
                    low_floor_bus=None,
                    boarding_assistance_available=True,
                    accessible_stop=True,
                    audio_announcements=True,
                    visual_displays=True,
                    accessibility_disclosure="Verified wheelchair accessible terminal with step-free ramps and boarding assistance.",
                    accessibility_source="bmtc_station_database",
                ),
            ),
            "stop-shivajinagar": BusStop(
                stop_id="stop-shivajinagar",
                name="Shivajinagar Bus Station",
                kannada_name="ಶಿವಾಜಿನಗರ ಬಸ್ ನಿಲ್ದಾಣ",
                latitude=12.9856,
                longitude=77.6057,
                accessibility=unknown_acc,
            ),
            "stop-electronic-city": BusStop(
                stop_id="stop-electronic-city",
                name="Electronic City Phase 1",
                kannada_name="ಎಲೆಕ್ಟ್ರಾನಿಕ್ ಸಿಟಿ",
                latitude=12.8452,
                longitude=77.6602,
                accessibility=AccessibilityMetadata(
                    status=AccessibilityStatus.ACCESSIBLE,
                    wheelchair_accessible=True,
                    low_floor_bus=None,
                    boarding_assistance_available=True,
                    accessible_stop=True,
                    audio_announcements=False,
                    visual_displays=False,
                    accessibility_disclosure="Verified wheelchair accessible stop with ramp access.",
                    accessibility_source="bmtc_station_database",
                ),
            ),
            "stop-bommanahalli": BusStop(
                stop_id="stop-bommanahalli",
                name="Bommanahalli",
                kannada_name="ಬೊಮ್ಮನಹಳ್ಳಿ",
                latitude=12.9029,
                longitude=77.6242,
                accessibility=unknown_acc,
            ),
            "stop-hsr-5th": BusStop(
                stop_id="stop-hsr-5th",
                name="HSR Layout Sector 5",
                kannada_name="ಎಚ್.ಎಸ್.ಆರ್ ಬಡಾವಣೆ",
                latitude=12.9198,
                longitude=77.6401,
                accessibility=unknown_acc,
            ),
            "stop-st-johns": BusStop(
                stop_id="stop-st-johns",
                name="St. John’s Hospital",
                kannada_name="ಸೇಂಟ್ ಜಾನ್ಸ್ ಆಸ್ಪತ್ರೆ",
                latitude=12.9290,
                longitude=77.6198,
                accessibility=unknown_acc,
            ),
            "stop-koramangala-bda": BusStop(
                stop_id="stop-koramangala-bda",
                name="Koramangala BDA Complex",
                kannada_name="ಕೋರಮಂಗಲ ಬಿ.ಡಿ.ಎ ಕಾಂಪ್ಲೆಕ್ಸ್",
                latitude=12.9345,
                longitude=77.6255,
                accessibility=unknown_acc,
            ),
            "stop-airport": BusStop(
                stop_id="stop-airport",
                name="Kempegowda Intl Airport (T2)",
                kannada_name="ವಿಮಾನ ನಿಲ್ದಾಣ",
                latitude=13.1986,
                longitude=77.7066,
                accessibility=AccessibilityMetadata(
                    status=AccessibilityStatus.ACCESSIBLE,
                    wheelchair_accessible=True,
                    low_floor_bus=None,
                    boarding_assistance_available=True,
                    accessible_stop=True,
                    audio_announcements=True,
                    visual_displays=True,
                    accessibility_disclosure="Airport terminal transit hub with full wheelchair and boarding assistance.",
                    accessibility_source="bmtc_station_database",
                ),
            ),
            "stop-brigade-road": BusStop(
                stop_id="stop-brigade-road",
                name="Brigade Road / MG Road",
                kannada_name="ಬ್ರಿಗೇಡ್ ರಸ್ತೆ",
                latitude=12.9738,
                longitude=77.6075,
                accessibility=unknown_acc,
            ),
        }

        # Corridor waypoints for smooth simulated movement
        self._waypoints: Dict[str, List[tuple[float, float, str]]] = {
            "bus-500d-1": [
                (12.9240, 77.6380, "HSR Layout BDA"),
                (12.9176, 77.6238, "Central Silk Board Junction"),
                (12.9152, 77.6120, "BTM Layout Water Tank"),
                (12.9180, 77.5980, "Jayadeva Hospital"),
                (12.9350, 77.5810, "South End Circle"),
                (12.9774, 77.5708, "Majestic (Kempegowda Bus Station)"),
            ],
            "bus-356-1": [
                (12.8452, 77.6602, "Electronic City Phase 1"),
                (12.9029, 77.6242, "Bommanahalli"),
                (12.9176, 77.6238, "Central Silk Board Junction"),
                (12.9290, 77.6198, "St. John’s Hospital"),
                (12.9420, 77.6010, "Dairy Circle"),
                (12.9856, 77.6057, "Shivajinagar Bus Station"),
            ],
            "bus-201r-1": [
                (12.9080, 77.5730, "Banashankari TTMC"),
                (12.9152, 77.6120, "BTM Layout Water Tank"),
                (12.9180, 77.5980, "Jayadeva Hospital"),
                (12.9510, 77.5860, "Lalbagh West Gate"),
                (12.9774, 77.5708, "Majestic (Kempegowda Bus Station)"),
            ],
            "bus-kia8-1": [
                (12.8452, 77.6602, "Electronic City Phase 1"),
                (12.9176, 77.6238, "Central Silk Board Junction"),
                (12.9198, 77.6401, "HSR Layout Sector 5"),
                (12.9540, 77.6980, "Marathahalli Bridge"),
                (13.0350, 77.5970, "Hebbal Flyover"),
                (13.1986, 77.7066, "Kempegowda Intl Airport (T2)"),
            ],
            "bus-g2-1": [
                (12.9070, 77.6850, "Sarjapur Wipro Campus"),
                (12.9230, 77.6480, "Agara Junction"),
                (12.9290, 77.6198, "St. John’s Hospital"),
                (12.9345, 77.6255, "Koramangala BDA Complex"),
                (12.9738, 77.6075, "Brigade Road / MG Road"),
            ],
        }

        self._bus_progress: Dict[str, float] = {
            "bus-500d-1": 0.85,  # Close to Silk Board
            "bus-356-1": 1.40,
            "bus-201r-1": 0.30,
            "bus-kia8-1": 1.10,
            "bus-g2-1": 1.80,
        }

        # Routes metadata
        self._routes: Dict[str, Route] = {
            "500D": Route(
                route_id="route-500d",
                route_number="500D",
                source="Kadugodi Bus Station",
                destination="Majestic (Kempegowda Bus Station)",
                stops=["HSR Layout BDA", "Central Silk Board Junction", "BTM Layout Water Tank", "Jayadeva Hospital", "South End Circle", "Majestic (Kempegowda Bus Station)"],
                estimated_duration=48,
                is_ac=True,
                bus_type="Vajra Electric",
            ),
            "356": Route(
                route_id="route-356",
                route_number="356",
                source="Electronic City Phase 1",
                destination="Shivajinagar Bus Station",
                stops=["Electronic City Phase 1", "Bommanahalli", "Central Silk Board Junction", "St. John’s Hospital", "Dairy Circle", "Shivajinagar Bus Station"],
                estimated_duration=42,
                is_ac=False,
                bus_type="BMTC Ordinary",
            ),
            "201R": Route(
                route_id="route-201r",
                route_number="201R",
                source="Banashankari TTMC",
                destination="Kempegowda Bus Station",
                stops=["Banashankari TTMC", "BTM Layout Water Tank", "Jayadeva Hospital", "Lalbagh West Gate", "Majestic (Kempegowda Bus Station)"],
                estimated_duration=36,
                is_ac=False,
                bus_type="BMTC Ordinary",
            ),
            "KIA-8": Route(
                route_id="route-kia8",
                route_number="KIA-8",
                source="Electronic City Phase 1",
                destination="Kempegowda Intl Airport (T2)",
                stops=["Electronic City Phase 1", "Central Silk Board Junction", "HSR Layout Sector 5", "Marathahalli Bridge", "Hebbal Flyover", "Kempegowda Intl Airport (T2)"],
                estimated_duration=75,
                is_ac=True,
                bus_type="Vayu Vajra",
            ),
            "G-2": Route(
                route_id="route-g2",
                route_number="G-2",
                source="Sarjapur Wipro Campus",
                destination="Brigade Road / MG Road",
                stops=["Sarjapur Wipro Campus", "Agara Junction", "St. John’s Hospital", "Koramangala BDA Complex", "Brigade Road / MG Road"],
                estimated_duration=35,
                is_ac=True,
                bus_type="Vajra Electric",
            ),
        }

        # Static bus definitions with live state attributes
        self._bus_definitions: Dict[str, dict] = {
            "bus-500d-1": {
                "route_number": "500D",
                "bus_type": "Vajra Electric",
                "destination": "Majestic (Kempegowda Bus Station)",
                "capacity": 50,
                "current_passengers": 39,
                "plate_number": "KA-01-F-4819",
                "speed_base": 26.0,
                "accessibility": AccessibilityMetadata(
                    status=AccessibilityStatus.ACCESSIBLE,
                    wheelchair_accessible=True,
                    low_floor_bus=True,
                    boarding_assistance_available=True,
                    accessible_stop=False,
                    audio_announcements=True,
                    visual_displays=True,
                    accessibility_disclosure="Low-floor electric bus with fold-out wheelchair ramp and audio announcements.",
                    accessibility_source="bmtc_fleet_registry",
                ),
            },
            "bus-356-1": {
                "route_number": "356",
                "bus_type": "BMTC Ordinary",
                "destination": "Shivajinagar Bus Station",
                "capacity": 52,
                "current_passengers": 28,
                "plate_number": "KA-57-F-1102",
                "speed_base": 31.0,
                "accessibility": AccessibilityMetadata(
                    status=AccessibilityStatus.NOT_ACCESSIBLE,
                    wheelchair_accessible=False,
                    low_floor_bus=False,
                    boarding_assistance_available=False,
                    accessible_stop=False,
                    audio_announcements=False,
                    visual_displays=False,
                    accessibility_disclosure="Standard high-floor bus with step entry. Not wheelchair accessible.",
                    accessibility_source="bmtc_fleet_registry",
                ),
            },
            "bus-201r-1": {
                "route_number": "201R",
                "bus_type": "BMTC Ordinary",
                "destination": "Kempegowda Bus Station",
                "capacity": 50,
                "current_passengers": 21,
                "plate_number": "KA-01-FA-9042",
                "speed_base": 22.0,
                "accessibility": AccessibilityMetadata(
                    status=AccessibilityStatus.NOT_ACCESSIBLE,
                    wheelchair_accessible=False,
                    low_floor_bus=False,
                    boarding_assistance_available=False,
                    accessible_stop=False,
                    audio_announcements=False,
                    visual_displays=False,
                    accessibility_disclosure="Standard high-floor bus with step entry. Not wheelchair accessible.",
                    accessibility_source="bmtc_fleet_registry",
                ),
            },
            "bus-kia8-1": {
                "route_number": "KIA-8",
                "bus_type": "Vayu Vajra",
                "destination": "Kempegowda Intl Airport (T2)",
                "capacity": 48,
                "current_passengers": 14,
                "plate_number": "KA-04-F-7731",
                "speed_base": 42.0,
                "accessibility": AccessibilityMetadata(
                    status=AccessibilityStatus.ACCESSIBLE,
                    wheelchair_accessible=True,
                    low_floor_bus=True,
                    boarding_assistance_available=True,
                    accessible_stop=False,
                    audio_announcements=True,
                    visual_displays=True,
                    accessibility_disclosure="Low-floor airport express coach with wheelchair ramp and luggage assistance.",
                    accessibility_source="bmtc_fleet_registry",
                ),
            },
            "bus-g2-1": {
                "route_number": "G-2",
                "bus_type": "Vajra Electric",
                "destination": "Brigade Road / MG Road",
                "capacity": 48,
                "current_passengers": 31,
                "plate_number": "KA-01-F-2940",
                "speed_base": 19.0,
                "accessibility": AccessibilityMetadata(
                    status=AccessibilityStatus.ACCESSIBLE,
                    wheelchair_accessible=True,
                    low_floor_bus=True,
                    boarding_assistance_available=True,
                    accessible_stop=False,
                    audio_announcements=True,
                    visual_displays=True,
                    accessibility_disclosure="Low-floor electric bus with wheelchair ramp.",
                    accessibility_source="bmtc_fleet_registry",
                ),
            },
        }

    def _interpolate_position(self, bus_id: str) -> tuple[float, float, float, str, float]:
        """Calculates interpolated lat, lon, heading, next stop, speed."""
        wps = self._waypoints[bus_id]
        prog = self._bus_progress[bus_id]

        idx = int(prog) % (len(wps) - 1)
        fraction = prog - int(prog)

        lat1, lon1, _ = wps[idx]
        lat2, lon2, next_stop_name = wps[idx + 1]

        cur_lat = lat1 + (lat2 - lat1) * fraction
        cur_lon = lon1 + (lon2 - lon1) * fraction

        # Direction calculation
        y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
        x = (
            math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
            - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1))
        )
        heading = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

        base_speed = self._bus_definitions[bus_id]["speed_base"]
        speed = round(base_speed + random.uniform(-3.0, 3.0), 1)

        return cur_lat, cur_lon, heading, next_stop_name, speed

    def tick_simulation(self):
        """Advances buses along waypoints and fluctuates passenger counts."""
        for bus_id in self._waypoints.keys():
            wps = self._waypoints[bus_id]
            max_idx = len(wps) - 1

            # Step forward
            new_prog = self._bus_progress[bus_id] + 0.02
            if new_prog >= max_idx:
                new_prog = 0.0  # Loop route
            self._bus_progress[bus_id] = new_prog

            # Slight passenger exchange (turnover)
            bdef = self._bus_definitions[bus_id]
            passenger_delta = random.choice([-2, -1, 0, 1, 2])
            new_passengers = max(5, min(bdef["capacity"], bdef["current_passengers"] + passenger_delta))
            bdef["current_passengers"] = new_passengers

    def reset_simulation(self):
        """Reset simulated bus positions and passenger counts back to initial demo values."""
        self._bus_progress = {
            "bus-500d-1": 0.85,
            "bus-356-1": 1.40,
            "bus-201r-1": 0.30,
            "bus-kia8-1": 1.10,
            "bus-g2-1": 1.80,
        }
        if "bus-500d-1" in self._bus_definitions:
            self._bus_definitions["bus-500d-1"]["current_passengers"] = 39
        if "bus-356-1" in self._bus_definitions:
            self._bus_definitions["bus-356-1"]["current_passengers"] = 28
        if "bus-201r-1" in self._bus_definitions:
            self._bus_definitions["bus-201r-1"]["current_passengers"] = 21
        if "bus-kia8-1" in self._bus_definitions:
            self._bus_definitions["bus-kia8-1"]["current_passengers"] = 14
        if "bus-g2-1" in self._bus_definitions:
            self._bus_definitions["bus-g2-1"]["current_passengers"] = 35

    def _build_bus_model(self, bus_id: str) -> Bus:
        bdef = self._bus_definitions[bus_id]
        lat, lon, heading, next_stop, speed = self._interpolate_position(bus_id)

        occ = OccupancyService.calculate_occupancy(
            bus_id, bdef["capacity"], bdef["current_passengers"]
        )

        # Calculate ETA to next stop
        wps = self._waypoints[bus_id]
        idx = int(self._bus_progress[bus_id]) % (len(wps) - 1)
        next_lat, next_lon, _ = wps[idx + 1]

        eta_res = ETAService.calculate_eta(
            bus_id=bus_id,
            route_number=bdef["route_number"],
            bus_lat=lat,
            bus_lon=lon,
            target_stop_name=next_stop,
            target_lat=next_lat,
            target_lon=next_lon,
            current_speed_kmh=speed,
        )

        # Calculate following stop along corridor
        following_idx = min(idx + 2, len(wps) - 1)
        following_stop = wps[following_idx][2] if following_idx != (idx + 1) else bdef["destination"]

        return Bus(
            bus_id=bus_id,
            route_number=bdef["route_number"],
            bus_type=bdef["bus_type"],
            destination=bdef["destination"],
            latitude=round(lat, 5),
            longitude=round(lon, 5),
            speed=speed,
            direction=round(heading, 1),
            capacity=bdef["capacity"],
            current_passengers=bdef["current_passengers"],
            occupancy_percentage=occ.occupancy_percentage,
            status="IN_SERVICE",
            next_stop=next_stop,
            following_stop=following_stop,
            distance_to_next_stop_km=round(eta_res.distance_km, 2),
            updated_at=datetime.utcnow(),
            plate_number=bdef["plate_number"],
            eta_minutes=eta_res.eta_minutes,
            available_seats=occ.available_seats,
            accessibility=bdef.get("accessibility"),
            crowd=crowd_service.get_crowd_metadata(
                identifier=bus_id,
                route_number=bdef["route_number"],
                is_simulated=True,
            ),
        )

    def get_accessibility_info(self, identifier: str) -> AccessibilityMetadata:
        """Lookup accessibility info for a bus, route, or stop. Returns strict unknown fallback if not verified."""
        ident_lower = identifier.strip().lower()
        # Check buses
        for bus_id, bdef in self._bus_definitions.items():
            if ident_lower in (bus_id.lower(), bdef["route_number"].lower()):
                return bdef.get("accessibility") or AccessibilityMetadata()
        # Check stops
        for stop_id, stop in self._stops.items():
            if ident_lower in (stop_id.lower(), stop.name.lower()):
                return stop.accessibility or AccessibilityMetadata()
        # Fallback unknown
        return AccessibilityMetadata(
            status=AccessibilityStatus.UNKNOWN,
            wheelchair_accessible=None,
            low_floor_bus=None,
            boarding_assistance_available=False,
            accessible_stop=False,
            audio_announcements=False,
            visual_displays=False,
            accessibility_disclosure="Accessibility information unavailable from the current transit data.",
            accessibility_source="simulated_corridor",
        )

    def get_crowd_info(self, identifier: str) -> CrowdMetadata:
        """Lookup crowd info for a bus, route, or stop with honest non-fabricated disclosures."""
        ident_lower = identifier.strip().lower()
        route_num = None
        for bus_id, bdef in self._bus_definitions.items():
            if ident_lower in (bus_id.lower(), bdef["route_number"].lower()):
                route_num = bdef["route_number"]
                break
        return crowd_service.get_crowd_metadata(
            identifier=identifier,
            route_number=route_num,
            is_simulated=True,
        )

    def get_incident_info(self, identifier: str) -> List[Incident]:
        """Lookup incidents affecting a bus, route, or stop."""
        ident_clean = identifier.strip()
        # Try route first
        incidents = incident_service.get_incidents(route_number=ident_clean, active_only=True)
        if not incidents:
            incidents = incident_service.get_incidents(stop_id_or_name=ident_clean, active_only=True)
        return incidents

    async def get_buses(self) -> List[Bus]:
        return [self._build_bus_model(bus_id) for bus_id in self._bus_definitions.keys()]

    async def get_bus(self, bus_id: str) -> Optional[Bus]:
        if bus_id not in self._bus_definitions:
            return None
        return self._build_bus_model(bus_id)

    async def get_bus_location(self, bus_id: str) -> Optional[BusLocation]:
        if bus_id not in self._bus_definitions:
            return None
        b = self._build_bus_model(bus_id)
        return BusLocation(
            bus_id=b.bus_id,
            route_number=b.route_number,
            latitude=b.latitude,
            longitude=b.longitude,
            speed=b.speed,
            direction=b.direction,
            updated_at=b.updated_at,
        )

    async def get_bus_route(self, bus_id: str) -> Optional[Route]:
        if bus_id not in self._bus_definitions:
            return None
        route_num = self._bus_definitions[bus_id]["route_number"]
        route = self._routes.get(route_num)
        if not route:
            return None
        wps = self._waypoints.get(bus_id, [])
        return Route(
            route_id=route.route_id,
            route_number=route.route_number,
            source=route.source,
            destination=route.destination,
            stops=route.stops,
            estimated_duration=route.estimated_duration,
            is_ac=route.is_ac,
            bus_type=route.bus_type,
            waypoints=[Coordinate(latitude=lat, longitude=lon) for lat, lon, _ in wps],
        )

    async def get_bus_stops(self, bus_id: str) -> List[BusStop]:
        if bus_id not in self._bus_definitions:
            return []
        route_num = self._bus_definitions[bus_id]["route_number"]
        route = self._routes.get(route_num)
        if not route:
            return []

        matched_stops: List[BusStop] = []
        for stop_name in route.stops:
            # Match stop object by name
            for s in self._stops.values():
                if s.name == stop_name or stop_name in s.name:
                    matched_stops.append(s)
                    break
        return matched_stops

    async def get_bus_occupancy(self, bus_id: str) -> Optional[Occupancy]:
        if bus_id not in self._bus_definitions:
            return None
        bdef = self._bus_definitions[bus_id]
        return OccupancyService.calculate_occupancy(
            bus_id, bdef["capacity"], bdef["current_passengers"]
        )

    async def get_nearby_stops(self, latitude: float, longitude: float, radius_km: float = 3.0) -> List[BusStop]:
        nearby: List[BusStop] = []
        for stop in self._stops.values():
            dist = haversine_distance_km(latitude, longitude, stop.latitude, stop.longitude)
            if dist <= radius_km:
                nearby.append(stop)
        return nearby

    async def get_eta(self, bus_id: str, target_stop_name: str = "Central Silk Board Junction") -> Optional[ETAEstimate]:
        if bus_id not in self._bus_definitions:
            return None
        b = self._build_bus_model(bus_id)

        target_lat = 12.9176
        target_lon = 77.6238
        matched_stop_name = target_stop_name
        for s in self._stops.values():
            if target_stop_name.lower() in s.name.lower():
                target_lat = s.latitude
                target_lon = s.longitude
                matched_stop_name = s.name
                break

        return ETAService.calculate_eta(
            bus_id=bus_id,
            route_number=b.route_number,
            bus_lat=b.latitude,
            bus_lon=b.longitude,
            target_stop_name=matched_stop_name,
            target_lat=target_lat,
            target_lon=target_lon,
            current_speed_kmh=b.speed,
        )

    def get_data_mode(self) -> str:
        return "simulated"

    def is_realtime(self) -> bool:
        return False

    def provider_name(self) -> str:
        return "mock"


# Global singleton instance of provider
mock_provider = MockTransitDataProvider()
