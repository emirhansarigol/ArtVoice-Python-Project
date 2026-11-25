# ArtVoice — Real-Time Messaging, Voice & Project Collaboration Backend

ArtVoice is a containerized, real-time communication and collaboration backend built with **FastAPI**. It combines WebSocket-based instant messaging, WebRTC voice/video call signaling, presence tracking, and role-based project/task management into a modular, production-oriented architecture.

## Key Features

- **Real-Time Messaging (WebSockets):** Dual-layer WebSocket architecture supporting both global user events (`/ws/global`) and channel-specific streams (`/ws/{channel_id}`) for group channels and Direct Messages (DMs).
- **Presence & Read Receipts:** Live online/offline user presence tracking and accurate unread message counters powered by **Redis** and timezone-aware read timestamps.
- **Voice & Video Calls:** Backend signaling infrastructure designed for real-time audio/video communication.
- **Project & Task Management:** Built-in CRUD endpoints for managing projects, tasks, assignees, and status transitions with Role-Based Access Control (`admin`, `project_manager`, `member`).
- **Media & File Storage:** S3-compatible object storage integration using **MinIO** for attachments and media files.
- **Asynchronous Processing:** Decoupled background workflows and event handling via **RabbitMQ**.
- **Authentication & Security:** Stateless **JWT** authentication with strict permission checks across REST and WebSocket endpoints.

## Tech Stack

| Layer | Technology |
| :--- | :--- |
| **Framework** | Python, FastAPI, Pydantic |
| **Database & ORM** | PostgreSQL, SQLAlchemy, Alembic |
| **Real-Time & Caching** | WebSockets, Redis (Presence & Unread State) |
| **Message Broker** | RabbitMQ |
| **Object Storage** | MinIO |
| **Containerization** | Docker, Docker Compose |

## Architecture Overview

```text
Client (Web / Mobile)
   │
   ├── REST API (Auth, Projects, Tasks, Channels, Media) ──► FastAPI Backend
   │                                                              │
   └── WebSockets (/ws/global, /ws/{channel_id}) ─────────────────┤
                                                                  ├──► PostgreSQL (Persistent Data)
                                                                  ├──► Redis (Presence & Unread Counts)
                                                                  ├──► RabbitMQ (Async Events)
                                                                  └──► MinIO (File & Media Storage)