"use client";

import { useState } from "react";

import { askChat, ingestMeeting, type ChatTurn } from "@/lib/api/chat";
import type { ChatAnswer, Meeting, Segment } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

interface ChatTabProps {
  meeting: Meeting;
  segments: Segment[];
  segmentsPending: boolean;
  ingested: boolean;
}

interface RenderedTurn {
  role: ChatTurn["role"];
  content: string;
  citations: ChatAnswer["citations"];
}

function IngestGate({
  meeting,
  segments,
  segmentsPending,
  onIngested,
}: {
  meeting: Meeting;
  segments: Segment[];
  segmentsPending: boolean;
  onIngested: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="max-w-xl space-y-4">
      <h2 className="text-lg font-semibold">Chat with this transcript</h2>
      <p className="text-muted-foreground text-sm">
        Index the transcript so the chat service can answer questions about it.
      </p>
      <Button
        disabled={pending || segmentsPending || segments.length === 0}
        onClick={async () => {
          if (segments.length === 0) return;
          setPending(true);
          setError(null);
          try {
            await ingestMeeting(meeting.id, segments);
            onIngested();
          } catch (e) {
            setError(e instanceof Error ? e.message : "Ingest failed");
          } finally {
            setPending(false);
          }
        }}
      >
        {pending ? "Ingesting\u2026" : "Ingest transcript"}
      </Button>
      {segmentsPending === false && segments.length === 0 && (
        <p className="text-muted-foreground text-sm">No transcript available for chat yet</p>
      )}
      {error !== null && <p className="text-sm text-red-300">{error}</p>}
    </div>
  );
}

function ChatPanel({ meeting }: { meeting: Meeting }) {
  const [turns, setTurns] = useState<RenderedTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [provider, setProvider] = useState("ollama");
  const [model, setModel] = useState("llama3");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (trimmed === "" || pending) return;

    const history: ChatTurn[] = turns.slice(-50).map(({ role, content }) => ({
      role,
      content,
    }));
    setTurns((prev) => [...prev, { role: "user", content: trimmed, citations: [] }]);
    setQuestion("");
    setPending(true);
    setError(null);
    try {
      const answer = await askChat(trimmed, meeting.id, history, provider, model);
      setTurns((prev) => [
        ...prev,
        {
          role: "assistant",
          content: answer.answer,
          citations: answer.citations,
        },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to ask");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex h-[60vh] flex-col gap-4">
      <div className="flex-1 space-y-4 overflow-y-auto">
        {turns.length === 0 && (
          <p className="text-muted-foreground text-sm">Ask a question about this meeting.</p>
        )}
        {turns.map((turn, index) => (
          <div key={index} className="space-y-1">
            <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
              {turn.role === "user" ? "You" : "Assistant"}
            </p>
            <p className="whitespace-pre-wrap">{turn.content}</p>
            {turn.role === "assistant" && turn.citations.length > 0 && (
              <ul className="text-muted-foreground space-y-1 border-l pl-3 text-xs">
                {turn.citations.map((citation) => (
                  <li key={citation.segment_id}>
                    <span className="font-mono">
                      [{citation.start_time ?? 0}-{citation.end_time ?? 0}]
                    </span>{" "}
                    {citation.text}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-4">
        <div className="space-y-1">
          <label className="text-muted-foreground text-sm" htmlFor="chat-provider">
            Provider
          </label>
          <Input
            id="chat-provider"
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
            className="w-40"
          />
        </div>
        <div className="space-y-1">
          <label className="text-muted-foreground text-sm" htmlFor="chat-model">
            Model
          </label>
          <Input
            id="chat-model"
            value={model}
            onChange={(event) => setModel(event.target.value)}
            className="w-40"
          />
        </div>
      </div>
      {error !== null && <p className="text-sm text-red-300">{error}</p>}
      <form className="flex flex-col gap-2" onSubmit={submit}>
        <Textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask a question about this meeting"
          aria-label="Question"
          rows={3}
          disabled={pending}
        />
        <Button type="submit" disabled={pending || question.trim() === ""}>
          {pending ? "Sending\u2026" : "Send"}
        </Button>
      </form>
    </div>
  );
}

export function ChatTab({
  meeting,
  segments,
  segmentsPending,
  ingested: initialIngested,
}: ChatTabProps) {
  const [ingested, setIngested] = useState(initialIngested);

  if (!ingested) {
    return (
      <IngestGate
        meeting={meeting}
        segments={segments}
        segmentsPending={segmentsPending}
        onIngested={() => setIngested(true)}
      />
    );
  }
  return <ChatPanel meeting={meeting} />;
}
