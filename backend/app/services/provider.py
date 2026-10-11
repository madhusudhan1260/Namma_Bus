from abc import ABC, abstractmethod
from typing import List, Optional
from ..models.transit import Bus, BusLocation, Route, BusStop, Occupancy, ETAEstimate


class TransitDataProvider(ABC):
    """
    Abstract interface for BMTC transit data sourcing.
    
    This clean abstraction allows MockTransitDataProvider to be seamlessly
    swapped with a future production BMTCTransitDataProvider (e.g. consuming
    official BMTC GTFS-RT or ITS portal APIs) without requiring any changes
    to API routes, service business logic, or the mobile application.
    """

    @abstractmethod
    async def get_buses(self) -> List[Bus]:
        """Retrieve all active buses currently in service."""
        pass

    @abstractmethod
    async def get_bus(self, bus_id: str) -> Optional[Bus]:
        """Retrieve details for a specific bus by ID."""
        pass

    @abstractmethod
    async def get_bus_location(self, bus_id: str) -> Optional[BusLocation]:
        """Retrieve live GPS coordinates and telemetry for a bus."""
        pass

    @abstractmethod
    async def get_bus_route(self, bus_id: str) -> Optional[Route]:
        """Retrieve the planned transit route for a bus."""
        pass

    @abstractmethod
    async def get_bus_stops(self, bus_id: str) -> List[BusStop]:
        """Retrieve ordered list of bus stops along the bus's route."""
        pass

    @abstractmethod
    async def get_bus_occupancy(self, bus_id: str) -> Optional[Occupancy]:
        """Retrieve real-time passenger crowd and seat availability."""
        pass

    @abstractmethod
    async def get_nearby_stops(self, latitude: float, longitude: float, radius_km: float = 3.0) -> List[BusStop]:
        """Retrieve bus stops in proximity to given coordinates."""
        pass

    @abstractmethod
    async def get_eta(self, bus_id: str, target_stop_name: str = "Central Silk Board Junction") -> Optional[ETAEstimate]:
        """Calculate dynamic ETA to a specific target stop."""
        pass

    def get_data_mode(self) -> str:
        """Return 'simulated' or 'realtime'."""
        return "simulated"

    def is_realtime(self) -> bool:
        """Return True if connected to live authorized telemetry, else False."""
        return False

    def provider_name(self) -> str:
        """Return human-readable provider identifier."""
        return "mock"
