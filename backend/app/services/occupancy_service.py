from ..models.transit import Occupancy


class OccupancyService:
    """
    Occupancy computation engine that evaluates passenger capacity,
    seat availability, and crowding tiers.
    """

    @staticmethod
    def calculate_occupancy(bus_id: str, capacity: int, current_passengers: int) -> Occupancy:
        safe_passengers = max(0, current_passengers)
        safe_capacity = max(1, capacity)

        available_seats = max(0, safe_capacity - safe_passengers)
        occupancy_percentage = min(100, round((safe_passengers / safe_capacity) * 100))

        if occupancy_percentage >= 75:
            level = "high"
        elif occupancy_percentage >= 50:
            level = "medium"
        else:
            level = "low"

        return Occupancy(
            bus_id=bus_id,
            capacity=safe_capacity,
            current_passengers=safe_passengers,
            available_seats=available_seats,
            occupancy_percentage=occupancy_percentage,
            occupancy_level=level,
        )
