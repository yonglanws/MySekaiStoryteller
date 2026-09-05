export interface AudioTimestampEntry {
  snippetIndex: number
  characterName: string
  text: string
  startTimeMs: number
  endTimeMs: number
  durationMs: number
  audioFilePath: string
}

export interface AudioTimestampManifest {
  entries: AudioTimestampEntry[]
  totalAudioDurationMs: number
  totalStoryDurationMs: number
}
