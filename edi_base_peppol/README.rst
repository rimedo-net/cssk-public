===================
EDI Base: Peppol
===================

Provider-neutral **Peppol BIS Billing 3.0** support: generate and receive
invoices / credit notes, and handle business responses (MLR today; Invoice
Response next), over **any** EDI transport provider.

The document standard lives here; the transport does not. A provider module
(e.g. ``edi_editel_peppol`` for Editel eXite, or a future ``edi_grit_peppol``
for GRiT Orion) supplies just two hooks on ``account.move``:

* ``_peppol_provider()`` — the provider key stamped on the outbound
  ``edi.message`` (``doc_family='peppol'``);
* ``_peppol_send(msg)`` — enqueue that message via the provider's connector.

Everything else — BIS3 UBL generation (Odoo core ``account.edi.xml.ubl_bis3``),
UBL classification, inbound vendor-bill creation, the MLR handling, the "Send
via Peppol" button, the Peppol Messages tab, and the settings — is here and
shared.

This module deliberately does **not** use Odoo's ``account_peppol`` /
``account_peppol_response``, whose send/receive path is hard-wired to Odoo's
own SAS access point.

Configuration
=============

#. Install a transport provider module (e.g. ``edi_editel_peppol``) and set its
   connector credentials.
#. On your company partner set **Peppol e-address (EAS)** + **Peppol Endpoint**;
   likewise on each customer/vendor.
#. Optionally, in *Settings ▸ EDI ▸ Peppol BIS3*, enable **Auto-send Peppol on
   Invoice Post** and/or pick the **Peppol Purchase Journal** for inbound bills.

Checking a contact on the Peppol network
========================================

**Check on Peppol** on the contact form (next to the Peppol address) and in
the header of a customer invoice or credit note asks the
Peppol network itself whether the contact is registered and receives BIS
Billing 3.0 invoices and credit notes. It needs no access point account, so it
works the same whichever provider the database sends through.

* **SML → SMP.** The participant id ``eas:endpoint`` is hashed
  (``base32(sha256(lower(id)))``) into a DNS name in OpenPeppol's SML zone
  ``participant.sml.prod.tech.peppol.org``; its U-NAPTR record names the
  participant's SMP, whose ServiceGroup lists the document types it receives.
* **Slovak VAT numbers.** Most Slovak participants are registered under the
  DIČ (``0245:<DIČ>``), while Odoo derives ``9950:SK<DIČ>`` from the VAT
  number. When the configured address is not on the network — or the contact
  has none — both spellings of the VAT number / DIČ are tried, and a hit
  becomes the contact's Peppol address (logged in the chatter).
* The answer is kept on the commercial partner (``peppol_smp_state``) with the
  address it was given for, and is shown as a badge only while that address is
  unchanged. Other code can call ``res.partner._peppol_smp_check()`` or the
  provider-neutral ``edi.peppol.smp._lookup("0245:…")`` directly.
* **"Could not check" is never "not registered".** A DNS timeout or an SMP that
  does not answer is an error dialog, and the stored answer is left alone.

System parameters:

* ``peppol.sml_zone`` — the SML zone; set
  ``participant.sml.test.tech.peppol.org`` for the Peppol test network.
* ``peppol.smp.doh_url`` — DNS-over-HTTPS JSON endpoint used when
  ``dnspython`` is not installed (the stock Odoo image lacks it); default
  ``https://cloudflare-dns.com/dns-query``. Only the hashed id is sent there.
