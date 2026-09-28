# ArogyaDesk

ArogyaDesk is a backend for the outpatient department of a small or mid-size clinic. It keeps one source of truth for doctor schedules, bookable slots, the live token queue, the consultation note, and the consultation bill.

The project was built by Sobhanbabu Katikapalle as the applied software project for the Backend Specialization.

## What a clinic can do

- A patient registers, sees open slots, and books one future slot.
- Reception creates walk-in bookings, checks patients in, marks no-shows, and records cash, UPI, or card payments.
- A doctor calls the next checked-in patient and writes a prescription.
- An admin creates clinics, departments, doctor accounts, and weekly schedules.
- Booking a slot is safe when many people tap the same slot together. The database update succeeds for one request and the others receive a conflict.
- Slot lists are cached. A booking removes the cached list after the database commit.
- Every booking, cancellation, completed visit, and payment is written to an outbox table in the same database transaction. A relay publishes those rows to Kafka when Kafka is enabled.

Money is stored as integer paise. A consultation fee of Rs 500 is `50000`.

Clinic clock times use India Standard Time (UTC+05:30). Event timestamps are stored in UTC.

## Project layout

```
app/
  main.py                 application entry
  factory.py              wiring, database engine, error handlers
  config.py               environment settings
  models.py               tables
  schemas.py              request and response bodies
  security.py             password hash and JWT
  cache.py                memory cache and Redis cache
  outbox.py               transactional outbox, Kafka publisher
  domain.py               roles, statuses, clinic clock
  services/               booking, queue, billing, and master data
  routers/                HTTP endpoints
  seed.py                 local demo data
db/schema.sql             MySQL schema
tests/                    API, visit, cache, and concurrency tests
docker-compose.yml        MySQL, Redis, and Kafka for local use
Dockerfile                image used by the deployment design
```

## Run the tests

From this folder, on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pytest
```

On macOS or Linux, activate the virtual environment with `source .venv/bin/activate` and run the same `pytest` command.

The tests use a temporary SQLite file. They do not need MySQL, Redis, or Kafka.

## Run the API locally

```powershell
copy .env.example .env
.\.venv\Scripts\uvicorn app.main:app --reload --port 8080
```

Open `http://127.0.0.1:8080/docs` for the interactive API reference.

With `SEED=true`, the first startup creates a demo clinic. These passwords are for a local demo only. Change them before any shared deployment.

| Email | Password | Role |
| --- | --- | --- |
| admin@arogyadesk.local | Admin@12345 | Admin |
| reception@arogyadesk.local | Reception@12345 | Receptionist |
| doctor@arogyadesk.local | Doctor@12345 | Doctor |
| patient@arogyadesk.local | Patient@12345 | Patient |

The demo clinic is CityCare OPD in Hyderabad. Dr. Meera Iyer has 15-minute slots from 09:00 to 12:00, Monday to Saturday, for the next seven days. The consultation fee is Rs 500.

## Run with MySQL, Redis, and Kafka

Start the infrastructure:

```powershell
docker compose up -d
```

Then point the API at it:

```powershell
$env:DATABASE_URL = "mysql+pymysql://arogya:arogya@localhost:3306/arogyadesk"
$env:REDIS_ENABLED = "true"
$env:KAFKA_ENABLED = "true"
$env:JWT_SECRET = "replace-this-with-a-long-random-secret-value"
$env:SEED = "true"
.\.venv\Scripts\uvicorn app.main:app --port 8080
```

`ENVIRONMENT=production` refuses to start when `JWT_SECRET` still contains the sample text `change-me`.

## Main API routes

All JSON fields use camel case. Protected routes expect `Authorization: Bearer <token>`.

| Method | Path | Who can call it |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | Public. Creates a patient. |
| POST | `/api/v1/auth/login` | Public. |
| GET | `/api/v1/auth/me` | Any signed-in user. |
| POST | `/api/v1/clinics` | Admin. |
| POST | `/api/v1/clinics/{id}/departments` | Admin. |
| POST | `/api/v1/admin/staff` | Admin. Creates a doctor or receptionist. |
| PUT | `/api/v1/doctors/{id}/schedule` | Admin. |
| POST | `/api/v1/doctors/{id}/slots` | Admin or receptionist. |
| GET | `/api/v1/doctors/{id}/slots?day=YYYY-MM-DD` | Any signed-in user. |
| POST | `/api/v1/appointments` | Patient (self), receptionist, or admin. |
| POST | `/api/v1/appointments/{id}/cancel` | Patient inside the cutoff, receptionist, or admin. |
| POST | `/api/v1/appointments/{id}/check-in` | Receptionist or admin. |
| POST | `/api/v1/doctors/{id}/queue/next?day=YYYY-MM-DD` | The assigned doctor. |
| POST | `/api/v1/appointments/{id}/encounter` | The consulting doctor. |
| POST | `/api/v1/invoices/{id}/payments` | Receptionist or admin. |

A booking body looks like this:

```json
{
  "slotId": 15,
  "patientId": 3
}
```

If the slot was taken by someone else, the API returns HTTP 409 and does not create a second appointment.

## How booking stays correct

`AppointmentService.book` updates the slot with one conditional statement:

```sql
UPDATE appointment_slot
SET status = 'BOOKED', version = version + 1
WHERE id = ? AND status = 'OPEN';
```

If no row changes, the slot is no longer open and the request is rejected. A unique `day_guard` value of `patient:doctor:date` stops the same patient from holding two active appointments with the same doctor on the same day. The queue token, the outbox row, and the audit row are inserted in that same transaction. The slot cache is cleared only after the commit succeeds.

Patients can cancel until two hours before the slot, unless `CANCEL_CUTOFF_HOURS` is changed. Cancelling a future slot makes it bookable again. A slot whose start time has passed is marked `BLOCKED` so it cannot be sold again.

The doctor calls the lowest token that is already checked in. A booked patient who has not arrived is not called. Walk-in patients booked by reception receive the next token, so they join the end of the queue.

## Tests that protect the main risk

`tests/test_concurrency.py` sends 16 overlapping booking calls at one slot and expects exactly one appointment. It also checks that the outbox relay delivers a message once and that the notification log ignores a duplicate delivery.

`tests/test_visit.py` walks a visit from booking through check-in, consultation, prescription, partial payment, and a paid invoice.

## Deployment design

The Dockerfile runs the API with uvicorn on port 8080. The intended cloud layout is an Application Load Balancer, an Elastic Beanstalk environment (or an EC2 Auto Scaling group) in private subnets, Amazon RDS for MySQL, ElastiCache for Redis, and Amazon MSK for Kafka. Security groups allow the load balancer to reach the API, and only the API to reach the database, cache, and broker. The report in `report/` describes this layout in full.

## Author

Sobhanbabu Katikapalle  
sobhanbabu.katikapalle@gmail.com
