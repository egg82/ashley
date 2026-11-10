import type { paths } from './schema';
import { answer } from './client';

type Cancelled = paths['/api/benches/{bench_id}/jobs/{job_id}/cancel']['post']['responses'][200]['content']['application/json'];

/** Cancels job `job` of bench `bench`; answers the job's state after it. */
export async function cancelJob(bench: number, job: number): Promise<Cancelled> {
  return answer(await fetch(`/api/benches/${bench}/jobs/${job}/cancel`, { method: 'POST' }), 200, 'POST /api/benches/{bench_id}/jobs/{job_id}/cancel');
}
