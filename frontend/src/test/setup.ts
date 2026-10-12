import "@testing-library/jest-dom/vitest";

// jsdom lacks ResizeObserver + requestAnimationFrame in some configurations;
// the graph view and timeline depend on both existing.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver ??= ResizeObserverStub;

globalThis.requestAnimationFrame ??= ((cb: (t: number) => void) =>
  setTimeout(() => cb(performance.now()), 16) as unknown as number) as typeof requestAnimationFrame;
globalThis.cancelAnimationFrame ??= ((id: number) =>
  clearTimeout(id as unknown as ReturnType<typeof setTimeout>)) as typeof cancelAnimationFrame;
