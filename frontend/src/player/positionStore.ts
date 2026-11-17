/** Tiny external store for the playhead position, so only subscribers re-render. */
export class PositionStore {
  private value = 0
  private listeners = new Set<() => void>()

  get = () => this.value

  set(v: number) {
    if (v === this.value) return
    this.value = v
    this.listeners.forEach((l) => l())
  }

  subscribe = (l: () => void) => {
    this.listeners.add(l)
    return () => {
      this.listeners.delete(l)
    }
  }
}
