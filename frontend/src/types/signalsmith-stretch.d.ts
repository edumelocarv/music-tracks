// Hand-written types for signalsmith-stretch@1.3.2 (the package ships none).
// Derived from node_modules/signalsmith-stretch/SignalsmithStretch.mjs.
declare module 'signalsmith-stretch' {
  export interface StretchSchedule {
    /** Audio context time at which this change is heard. */
    output?: number
    active?: boolean
    /** Position in the input buffer (seconds). */
    input?: number
    rate?: number
    semitones?: number
    tonalityHz?: number
    formantSemitones?: number
    formantCompensation?: boolean
    formantBaseHz?: number
    /** Loop disabled when loopStart === loopEnd. */
    loopStart?: number
    loopEnd?: number
  }

  export interface StretchConfig {
    blockMs?: number | null
    intervalMs?: number
    splitComputation?: boolean
    preset?: 'default' | 'cheaper'
  }

  export interface StretchNode extends AudioWorkletNode {
    /** Input time reported by the worklet; runs ahead of the heard audio (includes input latency). */
    inputTime: number
    schedule(change: StretchSchedule, adjustPrevious?: boolean): Promise<StretchSchedule>
    start(when?: number | StretchSchedule, offset?: number, duration?: number, rate?: number, semitones?: number): Promise<StretchSchedule>
    stop(when?: number): Promise<StretchSchedule>
    /** Appends buffers (one typed array per channel, equal lengths). Resolves to the new buffer end time (s). */
    addBuffers(buffers: Float32Array[], transfer?: Transferable[]): Promise<number>
    dropBuffers(toSeconds?: number): Promise<{ start: number; end: number }>
    /** Input + output latency in seconds. */
    latency(): Promise<number>
    configure(config: StretchConfig): Promise<void>
    setUpdateInterval(seconds: number, callback?: (inputTime: number) => void): Promise<void>
  }

  export default function SignalsmithStretch(
    context: BaseAudioContext,
    options?: AudioWorkletNodeOptions,
  ): Promise<StretchNode>
}
