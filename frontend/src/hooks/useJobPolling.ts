import useSWR from 'swr';
import { getJob } from '../api/client';
import type { Job } from '../types';

export function useJobPolling(jobId: string | undefined) {
  return useSWR<Job>(jobId ? `job-${jobId}` : null, () => getJob(jobId!), {
    refreshInterval: 2000,
  });
}
