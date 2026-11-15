import { useOutletContext } from "react-router-dom";
import type { SocketState } from "../hooks/useTripSocket";
import type { TripDetail } from "../lib/types";

export interface TripCtx { trip: TripDetail; socket: SocketState }
export const useTrip = () => useOutletContext<TripCtx>();
