# Questions for the NVOCC Team — End-to-End Flow

Use this document to gather requirements, business rules, and clarifications from the NVOCC (operations/business) team for each step of the AI Logistics SaaS flow. Tick off or annotate answers as you get them.

---

## 1. RFQ Intake (Customer Email → RFQ)

### Email ingestion
- Which email addresses/inboxes should we monitor for customer RFQs? One per org, or multiple (e.g. sales@, ops@)?
- Do we need to support Outlook/Microsoft 365 in addition to Gmail, or is Gmail-only acceptable for now?
- Should we auto-create an RFQ for every incoming email to the monitored inbox, or only when the AI classifies it as a rate/quote request?
- If a customer sends multiple emails in one thread (e.g. "Also need 20HC" in a reply), do we create a new RFQ or update the existing one?

### AI parsing / RFQ record
- What exact fields must we extract from the customer email? (e.g. POL, POD, container type, quantity, commodity, ready date, incoterms, special requirements?)
- Are there standard abbreviations or codes we must support (e.g. port codes vs full names, container types 20GP/40HC)?
- How do we handle incomplete RFQs (e.g. customer says "Need rates India to US" with no container count)? Do we create RFQ and flag "incomplete," or wait for clarification before creating?
- Do we need to store the raw email body and attachments in the RFQ, or only the parsed structured data?
- Should we link RFQ to an existing customer (by email/company) automatically, or always treat as "unknown" until they confirm via portal?

### Data stored (enquiries / rfq_messages)
- Who should be able to see RFQs in the system? (By role: e.g. sales, ops, admin—see Roles section.)
- Do we need an "RFQ source" (e.g. email vs manual entry vs API) for reporting?
- What is the lifecycle of an RFQ? (e.g. RFQ_CREATED → QUOTE_SENT → EXPIRED → CONVERTED_TO_ORDER?)
- Can RFQs be created or edited manually (not from email)? If yes, by which roles?

---

## 2. Quote Generation

### Inputs and calculation
- Which tariff/rate sources should be used for quoting? Only uploaded rate sheets, or also manual override rates, or contract rates from a separate system?
- How do we apply surcharges (THC, BAF, etc.)? Per container, per BL, percentage of ocean freight? Any rules (e.g. BAF only for certain trades)?
- Do we need margin/markup rules (e.g. add X% or $Y per container)? If yes, are they per customer, per trade, or global?
- What is the "valid for" period for a quote (e.g. 7 days, 14 days)? Is it configurable per org or per quote type?
- Should the quote be in a single currency (e.g. USD) or support multi-currency? If multi-currency, who chooses?

### Quote content and format
- What must appear on the quote sent to the customer? (e.g. Quote ID, line items, ocean freight, surcharges, total, validity, terms, our bank details?)
- Do we need a formal Quote PDF (generated document) or is an email body with structured data enough?
- Are there mandatory disclaimer/terms text that must appear on every quote?
- Do we need different quote "types" (e.g. spot quote vs contract quote) with different rules?

### Quote confirmation link
- What should the quote confirmation link look like? (e.g. `https://portal.company.com/confirm/QT-4821` or include a one-time token?)
- Should the link expire when the quote validity expires, or can the customer still open the form (with a "quote expired" message)?
- If the customer loses the email, do we need a "resend quote link" or "look up quote by email + quote ID" flow?

### Sending the quote
- Who sends the quote email—the system automatically after generation, or does a staff member review and click "Send"? If staff, which role(s)?
- Do we need to track "quote viewed" (e.g. customer opened the link) for analytics?
- Who can create, edit, or void a quote? Who can see all quotes (e.g. sales vs ops vs finance)?

---

## 3. Customer Portal Entry (Quote Link → Onboarding)

### Existing vs new customer
- How do we define "existing customer"? Same email address? Same company name? Same email domain?
- If existing customer: should they land on login only, or on a "Confirm quote" page that then asks for login?
- If new customer: do we require email verification before they can fill the shipment form, or can they fill first and verify later?
- For new customers, do we need to collect any additional info at signup (e.g. company name, phone) before showing the shipment form?

### Account creation and linking
- When a new customer creates an account from a quote link, how do we link them to the correct tenant/organization? (Quote already has org_id; do we need a separate "customer type" or "segment" per org?)
- Do we need to support "one customer, multiple NVOCCs" (same email can have accounts with different forwarders), or is it always one account per org?
- Should we create a "customer" (shipper/BCO) profile automatically when they sign up via quote link, or only when they submit the shipment form?

### Security and access
- Is the quote link itself considered "secret" (anyone with link can open it), or do we need a one-time token or password?
- After onboarding, how does the customer log in next time? Email + password only, or do we want magic link / OTP?
- Who can create "customer portal" accounts? Only via quote link, or can NVOCC staff create accounts for known shippers manually?

---

## 4. Shipment Confirmation Form (What Does the Form Contain?)

### Shipper information
- Which fields are mandatory? (Company name, address, contact name, email, phone?)
- Do we need multiple addresses (e.g. pickup address vs billing address)?
- Any format requirements (e.g. country as dropdown, phone with country code)?
- Do we pre-fill from quote/RFQ or from existing customer profile?

### Consignee information
- Same as shipper: mandatory fields, format, pre-fill?
- Do we need "notify party" as a separate section?

### Cargo information
- Mandatory: commodity, cargo description, weight, volume? Units (kg, cbm)?
- Is HS code mandatory or optional? If optional, when do we require it?
- How do we capture dangerous goods? (Checkbox + IMDG class, or free text?)
- Do we need temperature control (reefer) as a separate flag and temperature range?

### Container details
- Container type: from a fixed list (20GP, 40GP, 40HC, 45HC, etc.) or free text?
- Number of containers: per type (e.g. 2×40HC, 4×20GP) or only total?
- Gross weight: per container or total? Max weight limits we must validate?
- Volume (cbm): per container or total?
- Packaging type: dropdown (pallet, crate, loose) or free text? Mandatory?

### Route details
- Place of receipt vs port of loading: are both required, or can one be derived?
- Port of discharge vs final destination: same question.
- Do we accept port codes (e.g. INNSA) only, or full names, or both?
- Do we need "place of delivery" (e.g. CFS, door) as separate from final destination?

### Schedule preferences
- Cargo ready date: mandatory? Format (date only or date + time)?
- Preferred ETD: mandatory or optional? How do we express "flexibility" (e.g. ±3 days)?
- Do we need "required delivery date" (RDD) at destination? If yes, is it mandatory for allocation?

### Freight terms
- Incoterms: which ones do we support? (FOB, CIF, CFR, DAP, DDP, etc.) Mandatory?
- Prepaid vs collect: who pays ocean freight (shipper vs consignee)? Is this derived from incoterms or separate?

### Document upload
- Which documents are mandatory at submission? (Commercial invoice, packing list always? Others only for certain cargo?)
- Max file size and allowed formats (PDF, Excel, images)?
- Do we need MSDS for DG shipments? Any other conditional documents?
- Should we store documents in the same system or integrate with external DMS?

### Form behavior and validation
- Can the customer save a draft and come back later? If yes, how long do we keep drafts?
- Who can edit the form after submission—customer only until a deadline, or can NVOCC staff also edit?

---

## 5. Order Confirmation (Form Submit → Shipment Created)

### When is "order confirmed"?
- Is "order confirmed" the moment the customer submits the form, or only after NVOCC staff (or system) validates and accepts?
- Do we need a "pending confirmation" state where ops reviews before confirming?

### What we create on confirmation
- Do we create one "order" and one "shipment" per form submission, or can one order have multiple shipments?
- For "shipment": do we need separate entities for shipment vs booking (e.g. shipment = customer intent, booking = carrier allocation)?
- Should we create "containers" as placeholders (number and type) at confirmation, or only after allocation?

### Quote and order link
- Should every confirmed order link back to a quote (quote_id)? What if the customer came from a manual link or rebooking?
- If quote has expired but customer still submits, do we allow it with a warning or block?

### Status and notifications
- What exact status do we set on order/shipment at this step? (e.g. ORDER_CONFIRMED, SHIPMENT_CREATED?)
- Do we send an automatic email to the customer on confirmation? If yes, what should it say (e.g. "We have received your shipment details…")?
- Do we notify NVOCC ops (e.g. dashboard alert, email) when a new order is confirmed? Which role(s) receive the alert?
- Who can confirm or reject an order (if we have pending confirmation)? Who can cancel an order after confirmation?

---

## 6. Route Identification

### Data sources
- Where do vessel schedules come from? (Carrier APIs, manual upload, EDI, third-party schedule provider?)
- Do we have a single "vessel/schedule" database per org, or shared across orgs?
- How often are schedules updated? Do we need to handle "schedule changed" (ETD/ETA moved)?

### What "route" means
- Is a route = one sailing (vessel + voyage + ETD + ETA + POL + POD), or do we have multiple legs (e.g. transshipment)?
- For transshipment, do we need to store intermediate port and second vessel/voyage?
- Do we need "service" or "loop" (e.g. Far East – India loop) as a grouping for sailings?

### Matching shipment to routes
- How do we match a shipment request (POL, POD, ready date) to candidate routes? Exact port match only, or also "nearby" ports (e.g. range)?
- Do we filter by carrier (e.g. only carriers we have contracts with) at this step?

---

## 7. Capacity Planning Engine — Inputs and Logic

### Inputs
- Confirm: we need shipment request (POL, POD, container type, quantity, cargo ready date, required delivery date?), vessel schedules (with ETD, ETA, capacity?), and carrier contracts. Anything else?
- Is "required delivery date" (RDD) at destination mandatory for the engine? If customer did not provide it, do we assume "earliest possible" or "no constraint"?
- Do we have "capacity" per sailing (e.g. 20 slots left) in our data? If not, who provides it—carrier API, manual entry, or assumed unlimited until booking fails?

### Evaluation criteria
- How do we rank options? (Transit time first, then cost? Cost first? Customer preference?)
- Do we have "preferred carriers" or "blacklisted" carriers per org or per trade?
- Is splitting a shipment across multiple vessels (e.g. 8 on A, 4 on B) allowed, or do we prefer single-vessel allocation when possible?
- Do we consider transshipment only when direct is not available, or as equal options?

### Destination time (ETA)
- Confirm: we must not allocate to a sailing whose ETA at POD is after the customer's required delivery date. Correct?
- Do we need a buffer (e.g. ETA must be at least 2 days before RDD for customs)? If yes, what buffer per trade or per customer?

### Output
- What does the engine output? (Single best option, or top N options for ops to choose?)
- If multiple options are equally good, how do we break the tie (e.g. earliest ETD, lowest cost)?

---

## 8. Allocation Decision

### Who decides?
- Does the system auto-select the best option from the capacity engine, or does ops always choose from a shortlist?
- If auto-select: are there cases where we must always escalate to ops (e.g. DG, high value, first-time customer)?

### What we store
- When we "allocate," what exactly do we persist? (Shipment ID, vessel, voyage, ETD, ETA, number of containers, sailing ID?)
- Do we need to reserve "slots" with the carrier at this point, or is allocation only internal until we send booking request?

### Rollback
- Can we "de-allocate" and re-run the engine (e.g. if customer changes dates)? What is the business rule?

---

## 9. Capacity Allocation (When Feasible)

### Feasible allocation
- "Feasible" = engine found at least one option that meets capacity + ETD + ETA (and other rules). Agreed?
- Do we need to double-check with carrier (e.g. API "check availability") before marking BOOKED, or is our internal capacity data the source of truth?

### Status and tables
- After allocation we set status BOOKED and update capacity_allocations / shipment_bookings. Do we also decrease "available capacity" for that sailing in our DB?
- Who can see allocation details (vessel, voyage, ETD, ETA)—ops only, or also sales/customer via portal?

### Notifications
- Do we send "Booking confirmed" (or "Space reserved") email to customer at this step? What should it say?
- Do we notify ops when allocation is done (e.g. for them to proceed with carrier booking)?

---

## 10. Capacity Queue (When No Feasible Allocation)

### When do we queue?
- We put shipment in capacity queue when engine finds zero feasible options. Agreed?
- Do we also queue when we want "manual carrier negotiation" first (e.g. high volume), or is queue only for "no space"?

### Queue record and status
- Status WAITING_FOR_CAPACITY and table capacity_queue—any extra fields we need? (e.g. priority, requested ETD window, notes?)
- How do we define queue priority? (FIFO by request date, or by customer tier, or by required delivery date?)

### Customer communication
- Exact wording for "Space currently unavailable. Your shipment is on waitlist."—any legal or brand requirements?
- Do we give an estimated "we'll recheck by X date" or "we'll notify when space is available"?

---

## 11. Queue Reprocessing

### Triggers
- We re-run the queue when: new vessel schedule, carrier releases slots, shipment cancelled, manual override. Any other triggers (e.g. periodic job every 6 hours)?
- When we add a new sailing, do we trigger reprocess automatically or only on next scheduled run?

### Reprocess logic
- Process queue in priority order (FIFO or other)—agreed? Any "skip" rules (e.g. don't auto-allocate for customer X)?
- When we allocate from queue, do we notify the customer immediately ("Space confirmed") and then require them to confirm again, or is allocation itself the confirmation?

### Conflicts
- If two queued shipments need the last 10 slots (each needs 8), who gets priority? First in queue, or by RDD, or by customer?

---

## 12. Manual Carrier Negotiation

### When is it necessary?
- Only when shipment is in queue and no automatic allocation found? Or also when we prefer to call for "special" rates or ad-hoc space?
- Do we have a "request manual negotiation" button for ops, or is it implied whenever shipment is in queue for > X days?

### What ops do
- Do ops call/email the carrier, get confirmation, then enter in our system (e.g. "carrier confirmed 12 slots on Vessel X")? How do we capture that—free text note or structured "override" (vessel, voyage, slots)?
- Do we need "capacity_override" as a flag that means "don't auto-allocate; ops will set allocation manually"?

### After override
- Once ops sets capacity override (or manual allocation), does the system then continue the rest of the flow (booking lock, SI, BL, etc.) automatically?

---

## 13. Booking Lock

### When do we lock?
- Lock after allocation (or manual allocation) is confirmed. Do we also need carrier's formal booking number before we lock?
- Can we "unlock" to change vessel/voyage (e.g. carrier changed sailing)? If yes, who can do it and under what conditions?

### What we store
- Carrier, vessel, voyage, ETD, ETA, container allocation (number and type). Anything else (e.g. booking reference from carrier, cut-off date)?
- Do we need to store "free time" (e.g. 7 days free at destination) for demurrage calculation later?

### Status
- After lock we set BOOKING_CONFIRMED. Is this the same as "space confirmed" or do we have another status (e.g. BOOKING_SENT_TO_CARRIER)?

---

## 14. Shipping Instructions (SI)

### Generation
- SI is auto-generated from shipment data (parties, cargo, containers, route). Agreed? Any fields that must be manually edited every time (e.g. special instructions)?
- Do we have a standard SI template (format, sections)? Who provides it—ops or template per carrier?
- Do we need different SI for different carriers (e.g. Maersk vs MSC format)?

### Storage and sharing
- Where do we store the generated SI? (Our DB, and optionally send to carrier portal/API?)
- Do we send SI to the customer for approval before sending to carrier, or send to carrier directly?
- Do we need versioning (SI v1, v2 after amendment)?

---

## 15. Container Registration

### When do we assign numbers?
- After booking lock, when do we get container numbers? (From carrier after we send SI? From our own pool?)
- Do we allow "placeholder" container numbers (e.g. to be updated when carrier assigns)?

### What we store
- Container number, type, seal number, gross weight. Anything else (e.g. tare weight, VGM)?
- Do we need to support multiple events per container (e.g. empty picked, full at gate, loaded on vessel) in container_events?

### Who updates
- Who can add/update container numbers and events—ops only, or also from carrier EDI/API? Any role restrictions (e.g. only "ops lead" can correct container numbers)?

---

## 16. Master Bill of Lading (MBL)

### When do we generate?
- After SI sent and/or containers assigned? Or after a specific carrier confirmation?
- Do we generate MBL draft for ops to review before sending to customer, or auto-send?

### Content and format
- What data must be on the MBL? (Shipper, consignee, notify, vessel, voyage, POL, POD, containers, cargo description, freight terms, etc.)
- Do we have a template per carrier or one standard format? Who provides templates?
- Do we need House BL (HBL) in addition to MBL (e.g. for NVOCC as carrier)? If yes, same questions for HBL.
- Who can generate, approve, or amend the MBL in the system? Who can download or send it to the customer?

### Storage and delivery
- Where do we store the final MBL (signed)? Our DB + file storage (e.g. S3)? Do we push to customer portal for download?
- Do we send MBL to customer by email automatically, or only make it available in portal?

---

## 17. Invoice Generation

### When do we generate invoice?
- After BL confirmation? Or after shipment departed? Any other trigger?
- Do we have proforma invoice at quote/order stage and then final invoice after BL?

### What we charge
- Ocean freight (from quote/rate), local charges (THC, documentation, etc.), other surcharges. Full list of charge types we need to support?
- Who defines the list of charge types and rules (per org, per trade)?
- Do we need currency conversion (e.g. charge in USD, display in EUR for EU customer)?
- Who can create, edit, or void an invoice? Who can see cost/margin data (e.g. finance only vs ops)?

### Format and storage
- Invoice PDF: do we have a template? Who provides it?
- Do we store invoice in DB (invoices, invoice_items) and also generate PDF for download/email?
- Do we send invoice to customer by email and/or show in portal? Any approval workflow (e.g. customer must acknowledge)?
- Do we track payment status (e.g. sent, paid, overdue)? Who can record payment or mark invoice as paid?

---

## 18. Shipment Tracking

### Event sources
- Where do tracking events come from? (Carrier EDI, carrier API, port community system, manual entry by ops?)
- Do we need to normalize event types (e.g. "DEPOT_IN," "LOADED_VESSEL," "VESSEL_SAILED") from different carrier codes?

### What we store
- For each event: type, description, location, timestamp. Anything else (e.g. vessel position, next port)?
- Do we store at container level, shipment level, or both? (e.g. "Container MSCU123: loaded" vs "Shipment: vessel sailed.")

### Updates and frequency
- How often do we poll or receive updates from carrier/port? Real-time push or batch (e.g. daily)?
- Who can add manual events (e.g. "Customs cleared")—ops only? Any approval?

---

## 19. Customer Portal — Tracking View

### What customer sees
- Shipment status, container list, vessel name, voyage, ETD, ETA, tracking timeline. Anything else (e.g. documents, invoices)?
- Do we show "live" vessel position on a map, or only event list?
- Do we show BL and invoice for download in the same view? Any restrictions (e.g. invoice only after payment)?

### Notifications to customer
- Which events trigger a notification (e.g. "Vessel sailed," "Arrived at destination," "Delivered")? Full list?
- Channel: email only, or also in-app/portal notification?

---

## 20. Notifications (System-Wide)

### Events that trigger notifications
- List all: booking confirmed, capacity waitlist, space confirmed, SI sent, BL generated, invoice issued, vessel departed, vessel arrived, delivered, other?
- For each event: who is notified (customer, ops, sales)? Email, portal, or both?
- Do we need webhooks for external systems (e.g. customer ERP) for certain events?

### Content and branding
- Do we have email templates per event? Who provides copy and design?
- Do we need to support multiple languages for customer emails?

### Failure handling
- If email fails (bounce, invalid address), do we retry? Do we flag in portal or alert ops?

---

## 21. Shipment Closure

### When do we close?
- After "delivered" event? Or after customer confirms receipt? Or after final invoice paid?
- Do we need a manual "Close shipment" action by ops, or automatic after X days from delivery?

### What we do on closure
- Set shipment_status = CLOSED. Do we also lock the record (no more edits)?
- Profit calculation: what formula? (Revenue from invoice − cost from carrier/operational cost?) Do we store profit per shipment for reporting?
- Audit logs: what must we keep (e.g. who changed what, when)? Retention period?
- Analytics: which metrics do we need (e.g. volume by trade, by customer, margin, transit time)?

### Who can close and reopen
- Who can mark a shipment as CLOSED (which role)? Is it automatic or always manual?
- Can a closed shipment be reopened (e.g. claim, dispute)? If yes, who can do it and under what conditions?

---

## 22. Roles and ERP Access Control (Who Can Access What, at What Level)

### Role definitions
- What are all the internal user roles in the ERP? (e.g. Super Admin, Tenant Admin, Ops Manager, Ops Executive, Sales, Finance, Customer Service, Read-Only Auditor.) Please list each role and a one-line description of their job.
- Is "Customer" (shipper/BCO using the customer portal) considered a role in the same system, or a separate application with its own access rules?
- Do we need sub-roles or permissions within a role? (e.g. Ops Executive A can allocate but not override; Ops Executive B can override.)

### Access by module / screen
For each area below, who can **view**, **create**, **edit**, **delete**, and **approve** (if applicable)?

- **RFQs / Inquiries:** Which roles can see the list? See detail? Create manually? Assign or change status?
- **Quotes:** Which roles can create, edit, send, void quotes? Can sales see all quotes or only their own/customers?
- **Rate sheets:** Who can upload, view, edit, delete rate sheets? Can sales see rate sheets or only use them indirectly (e.g. via quotes)?
- **Customers (shipper/BCO profiles):** Who can create, edit, deactivate customers? Who can set portal password or send invite?
- **Orders / Shipments:** Who can see all orders vs only assigned/team orders? Who can confirm, cancel, or change shipment details?
- **Capacity queue:** Who can view the queue? Who can reprocess, set priority, or add manual allocation/override?
- **Allocation / Booking:** Who can allocate, lock booking, or change vessel/voyage after allocation?
- **Shipping instructions:** Who can generate, edit, send SI? Who can approve before sending to carrier?
- **Containers / BL:** Who can register containers, generate BL, amend BL, release to customer?
- **Invoices:** Who can create, edit, send, void invoices? Who can see cost and margin (finance only)?
- **Tracking:** Who can add or edit tracking events manually? Who can see full tracking history?
- **Reports / Analytics:** Who can access dashboards, profit reports, volume reports? Any role restricted to "own" data only?
- **Admin / Settings:** Who can manage users, roles, invitations, organization settings, email settings, API keys? Super Admin only or Tenant Admin too?

### Data scope (visibility level)
- Do some roles see only a **subset** of data? (e.g. by branch, by region, by "assigned customers," by trade lane.)
- If we have branches/teams: can Mumbai ops see Delhi shipments or only their own? Can sales see only customers assigned to them?
- Does "admin" mean one global super-admin across all tenants, or one admin per tenant (organization)? Can a tenant have multiple admins?

### Customer portal (external users)
- What can a customer (shipper) see and do in the portal? (e.g. view own shipments only, track, download BL/invoice, upload documents, raise request.) List allowed actions.
- Can a customer see historical shipments (e.g. last 2 years) or only active ones?
- Can we restrict certain customers from seeing cost/invoice (e.g. show only "documents" and "tracking")?

### Approval workflows (if any)
- Are there steps that require **approval** by a different role? (e.g. quote above $X needs manager approval; BL release needs ops lead; invoice above $Y needs finance approval.) List each and who approves.
- Can approvals be delegated (e.g. manager on leave → deputy approves)?

### Audit and compliance
- Do we need to log "who did what" (e.g. user X confirmed order Y at time Z)? For which actions?
- Who can access audit logs—Super Admin only, or also Tenant Admin for their org?
- Any regulatory requirement to restrict access by role (e.g. finance cannot edit BL; ops cannot edit invoice amount)?

---

## 23. General / Cross-Cutting

### Multi-tenancy
- One tenant = one NVOCC organization? Can one group have multiple brands/legal entities under one tenant?
- Do we need white-label (different logo/domain per tenant for customer portal)?

### Integrations
- Which external systems do we need to integrate? (Carrier booking portals, accounting/ERP, customs, DMS?)
- Do we need to expose APIs for customers (e.g. get tracking by shipment ID)?

### Compliance and legal
- Any data retention or GDPR-like requirements (e.g. delete customer data after X years)?
- Do we need audit trail for "who saw what" (e.g. who downloaded BL)?

### Edge cases
- What happens if customer submits form but quote has expired? Allow with warning or block?
- What if the same customer has two RFQs and we send two quote links—can they have two accounts or one account with two "pending" shipments?
- What if allocation fails after order is confirmed—do we notify customer and ask for new dates, or put in queue automatically without asking?
- When should a shipment be escalated to manual handling (e.g. DG, high value, exception)? Who can trigger or clear escalation?

---

*End of questions. Use this document in workshops or interviews with the NVOCC team; update with answers and new questions as the product evolves.*