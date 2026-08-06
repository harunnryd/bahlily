export const SERVICES = {
  orchestration: "http://127.0.0.1:8001",
  transcription: "http://127.0.0.1:8002",
  storage: "http://127.0.0.1:8003",
  export: "http://127.0.0.1:8004",
  chat: "http://127.0.0.1:8005",
} as const;

export type ServiceName = keyof typeof SERVICES;
