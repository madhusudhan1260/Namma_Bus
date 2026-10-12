import { Router, Request, Response, NextFunction } from 'express';
import prisma from '../db/prisma';

const router = Router();

/**
 * GET /api/fares?from=<stop id>&to=<stop id>[&route=<route number or id>]
 * Zone-to-zone fare from the imported GTFS fare_rules / fare_attributes (bmtc-gtfs).
 * A route-specific rule wins over the network-wide rule. 404 when the feed has no fare for the pair.
 */
router.get('/', async (req: Request, res: Response, next: NextFunction) => {
  try {
    const from = String(req.query.from || '').trim();
    const to = String(req.query.to || '').trim();
    const route = String(req.query.route || '').trim();
    if (!from || !to) {
      return res.status(400).json({ status: 'ERROR', message: 'from and to stop ids are required' });
    }
    const [origin, dest] = await Promise.all([
      prisma.stop.findFirst({ where: { OR: [{ id: from }, { stopId: from }] }, select: { id: true, name: true, zoneId: true } }),
      prisma.stop.findFirst({ where: { OR: [{ id: to }, { stopId: to }] }, select: { id: true, name: true, zoneId: true } }),
    ]);
    if (!origin || !dest) {
      return res.status(404).json({ status: 'ERROR', message: 'Stop not found' });
    }
    if (!origin.zoneId || !dest.zoneId) {
      return res.status(404).json({ status: 'ERROR', message: 'Fare zone unavailable for these stops in the GTFS feed' });
    }
    let routeId: string | null = null;
    if (route) {
      const r = await prisma.route.findFirst({ where: { OR: [{ id: route }, { routeShortName: route }] }, select: { id: true } });
      routeId = r?.id ?? null;
    }
    const candidates = await prisma.fare.findMany({
      where: {
        originStage: origin.zoneId,
        destStage: dest.zoneId,
        OR: routeId ? [{ routeId }, { routeId: null }] : [{ routeId: null }],
      },
    });
    const fare = candidates.find((f) => f.routeId && f.routeId === routeId) || candidates.find((f) => !f.routeId);
    if (!fare) {
      return res.status(404).json({ status: 'ERROR', message: 'No fare in the GTFS feed for this stop pair' });
    }
    res.json({
      status: 'SUCCESS',
      data: {
        fareAmount: fare.fareAmount,
        currency: fare.currency,
        originStop: origin.name,
        destinationStop: dest.name,
        originZone: origin.zoneId,
        destinationZone: dest.zoneId,
        source: 'GTFS_FARE_RULES',
        disclaimer: 'Fare from the community bmtc-gtfs feed; it may differ from the fare charged by BMTC.',
      },
    });
  } catch (err) {
    next(err);
  }
});

export default router;
