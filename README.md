# Fikr-e-Islam — Internet Archive Backend

A **FastAPI** microservice that wraps the [official `internetarchive` Python library](https://archive.org/services/docs/api/internetarchive/index.html) to provide secure, standard Internet Archive operations for the Fikr-e-Islam CMS.

## Why Python Backend?

The official `internetarchive` library handles:
- **Automatic retries** on 503 SlowDown errors
- **Proper S3 auth** with session management
- **Derive control** via the Tasks API
- **Metadata patches** using the official Metadata Write API
- **File operations** (copy, move, delete) with cascade support

## Quick Start

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your IA credentials and API secret

# 4. Run the server
python run.py
# → Server at http://localhost:8000
# → API docs at http://localhost:8000/docs
```

## API Endpoints

All endpoints require `Authorization: Bearer <API_SECRET_KEY>` header.

| Method   | Endpoint          | Description                      |
|----------|-------------------|----------------------------------|
| `POST`   | `/api/ia/upload`  | Upload file + cover to IA        |
| `PATCH`  | `/api/ia/metadata`| Update item metadata             |
| `POST`   | `/api/ia/rename`  | Rename a file in an IA item      |
| `DELETE` | `/api/ia/file`    | Delete a single file             |
| `DELETE` | `/api/ia/item`    | Delete all files in an item      |
| `POST`   | `/api/ia/derive`  | Trigger IA derive                |
| `GET`    | `/health`         | Health check                     |

### Upload (multipart/form-data)
```
POST /api/ia/upload
Content-Type: multipart/form-data

Fields:
  file:                Main media file
  metadata:            JSON string { title, speaker?, media_type?, contentType? }
  coverFile?:          Optional cover image
  existingIdentifier?: Reuse an existing IA item
```

### Metadata Update
```json
PATCH /api/ia/metadata
{
  "ia_url": "ia://fikreislam-speaker-abc123/file.mp3",
  "title": "New Title",
  "speaker": "Speaker Name",
  "contentType": "آڈیو"
}
```

## Environment Variables

| Variable         | Description                              |
|------------------|------------------------------------------|
| `IA_ACCESS_KEY`  | Internet Archive S3 access key           |
| `IA_SECRET_KEY`  | Internet Archive S3 secret key           |
| `API_SECRET_KEY` | Shared secret for frontend auth          |
| `HOST`           | Server host (default: `0.0.0.0`)         |
| `PORT`           | Server port (default: `8000`)            |

## Project Structure

```
fikreislam-backend/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app with CORS & lifespan
│   ├── config.py         # Settings from env vars
│   ├── auth.py           # Bearer token verification
│   ├── schemas.py        # Pydantic request/response models
│   ├── ia_service.py     # Core IA operations (official library)
│   └── routes.py         # API endpoints
├── requirements.txt
├── run.py               # Uvicorn entry point
├── .env.example
└── .gitignore
```
