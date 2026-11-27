# Notification service requirements

## 1. Roles

Customer, operator.

## 2. Requirements

FR-1. The system shall send a push notification to the customer within 5 seconds of a debit.

FR-2. The operator shall see the delivery status: sent, delivered, failed.

FR-3. On failure the system retries up to 3 times every minute.

FR-4. The customer may disable notifications in profile settings.

## 3. Interfaces

API POST /notify accepts client_id, amount, currency.
