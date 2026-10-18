# Part B: Design write-up

## 1. Your concurrency choice. How does your code prevent double-booking? Why this approach over the alternatives? Where would it break?

- We use `BEGIN IMMEDIATE` to start a transaction. If everything succeeds, the transaction is committed; if an error occurs, it is rolled back.
- This is a simple approach that works well for a POC. In production, we can use concurrency techniques such as row-level locking or optimistic versioning.
- If needed, Redis can provide distributed locks for a multi-instance application.

## 2. Scale: 50 cities, 5,000 technicians, 200,000 bookings a day, and 10x Monday-morning traffic. What changes first, and what would you measure?

- Use concurrency techniques such as row-level locking or optimistic versioning.
- Partition or shard high-traffic areas; if needed, use separate tables for particularly busy areas.
- Store availability data and slots in Redis, and update them after each booking using Kafka events.

## 3. Availability performance: How would you keep `GET /availability` fast without showing customers slots that are already gone?

- Add indexes to columns used in joins.
- Partition or shard high-traffic areas; if needed, use separate tables for particularly busy areas.
- Store availability data and slots in Redis, and update them after each booking using Kafka events.

## 4. Notifications: How do you send customer WhatsApp/SMS and technician push notifications without slowing or failing booking when a provider is slow or down?

- When a booking is created, publish a Kafka event. Another microservice can consume it and send the SMS or WhatsApp confirmation and technician push notification.
- We can use multiple providers. The consumer can check each provider's failure rate, stored in Redis, and choose the provider with the lowest failure rate.

## 5. Change you didn't plan for: What in your current model makes technician reassignment easy or hard?

- Technician leave or unavailability after a certain time is not currently accounted for.
- Add the ability to cancel bookings when a technician needs to be reassigned.

## 6. What you'd do next if you had another week, and why?

- Implement the suggestions above in a multi-microservice setup.
