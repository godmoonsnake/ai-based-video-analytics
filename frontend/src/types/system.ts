// System-level types: camera registry + stack health.

/** Camera registry entry (backend /cameras). x/y are site-plan coordinates. */
export interface Camera {
  id: string;
  name: string;
  site_id: string;
  x: number | null;
  y: number | null;
}

/** Backend /health response. */
export interface HealthStatus {
  status: string;
  database: boolean;
}
