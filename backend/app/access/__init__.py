"""
Namma Bus Access module: accounts, role-based access control, passenger eligibility (identity / face
verification, student passes verified by colleges), backend-priced tickets and conductor validation.

Self-contained so it can be mounted into the existing Namma Bus FastAPI app (under /api/access) without
touching live-bus tracking, routes, stops, journey planning or the NammaRoute integration.
See docs in backend/app/access/README.md.
"""
