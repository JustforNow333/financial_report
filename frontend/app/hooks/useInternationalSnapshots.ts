"use client";

import useSWR from "swr";

import { ApiError, fetcher } from "../lib/api";
import type { InternationalSnapshotsResponse } from "../lib/types";

type UseInternationalSnapshotsResult = {
  snapshotsData?: InternationalSnapshotsResponse;
  snapshotsError: unknown;
  snapshotsLoading: boolean;
  noSnapshotsYet: boolean;
};

export function useInternationalSnapshots(limit: number): UseInternationalSnapshotsResult {
  const { data, error, isLoading } = useSWR<InternationalSnapshotsResponse>(
    `/api/international/snapshots/latest?limit=${limit}`,
    fetcher,
    {
      refreshInterval: 60_000,
      revalidateOnFocus: false,
      shouldRetryOnError: false,
    }
  );

  return {
    snapshotsData: data,
    snapshotsError: error,
    snapshotsLoading: isLoading,
    noSnapshotsYet: error instanceof ApiError && error.status === 404,
  };
}
