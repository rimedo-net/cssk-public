"""Peppol participant lookup (SML → SMP) and the partner check, offline.

DNS and HTTP are patched at the model's own seams (``_naptr_records``,
``_fetch_service_group``), plus the DoH parser fed real answer shapes.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.edi_base_peppol.models.peppol_smp import (
    DOC_CREDIT_NOTE,
    DOC_INVOICE,
    DOC_INVOICE_RESPONSE,
    EdiPeppolSmp,
    PeppolLookupError,
)

SMP = "https://smp.example.sk"


def service_group(participant, doc_types):
    refs = "".join(
        '<smp:ServiceMetadataReference href="%s/iso6523-actorid-upis%%3A%%3A%s'
        '/services/busdox-docid-qns%%3A%%3A%s"/>' % (
            SMP, participant.replace(":", "%3A"),
            d.replace(":", "%3A").replace("#", "%23"))
        for d in doc_types)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<smp:ServiceGroup xmlns:smp="http://busdox.org/serviceMetadata/publishing/1.0/"'
        ' xmlns:tid="http://busdox.org/transport/identifiers/1.0/">'
        '<tid:ParticipantIdentifier scheme="iso6523-actorid-upis">%s'
        '</tid:ParticipantIdentifier>'
        '<smp:ServiceMetadataReferenceCollection>%s'
        '</smp:ServiceMetadataReferenceCollection></smp:ServiceGroup>'
        % (participant, refs)).encode()


class TestPeppolSmp(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.smp = cls.env["edi.peppol.smp"]
        cls.sk = cls.env.ref("base.sk")
        # participant id (lower) -> ServiceGroup bytes; absent = not on Peppol
        cls.network = {}

    def setUp(self):
        super().setUp()
        self.network.clear()
        self.asked = []
        network, asked = self.network, self.asked
        # Map each SML hostname back to the participant it was built from.
        hostnames = {}
        orig_hostname = EdiPeppolSmp._sml_hostname

        def sml_hostname(model, participant):
            name = orig_hostname(model, participant)
            hostnames[name] = participant.lower()
            return name

        def naptr(model, hostname):
            participant = hostnames[hostname]
            asked.append(participant)
            if participant not in network:
                return []
            return [(100, 10, "U", "Meta:SMP", "!.*!%s!" % SMP)]

        def fetch(model, smp_url, participant):
            return network.get(participant.lower())

        for name, fn in (("_sml_hostname", sml_hostname),
                         ("_naptr_records", naptr),
                         ("_fetch_service_group", fetch)):
            patcher = patch.object(EdiPeppolSmp, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def register(self, participant, doc_types=(DOC_INVOICE, DOC_CREDIT_NOTE)):
        self.network[participant.lower()] = service_group(participant, doc_types)

    def partner(self, **vals):
        vals.setdefault("name", "Odberateľ s.r.o.")
        vals.setdefault("country_id", self.sk.id)
        vals.setdefault("is_company", True)
        return self.env["res.partner"].create(vals)

    # -- the SML hostname and NAPTR parsing ------------------------------
    def test_sml_hostname_is_base32_sha256_in_the_openpeppol_zone(self):
        patch.stopall()  # the real hostname, not the recording wrapper
        self.assertEqual(
            self.smp._sml_hostname("0245:2023489446"),
            "W65WJHWSJKGSUIB2DKN4BPSCVPO4NWV4U6LSNZTPUWSDJBUEW7VQ"
            ".iso6523-actorid-upis.participant.sml.prod.tech.peppol.org")
        self.env["ir.config_parameter"].sudo().set_param(
            "peppol.sml_zone", "participant.sml.test.tech.peppol.org.")
        self.assertTrue(self.smp._sml_hostname("0245:2023489446").endswith(
            ".iso6523-actorid-upis.participant.sml.test.tech.peppol.org"))
        # Identifiers are case-insensitive.
        self.assertEqual(self.smp._sml_hostname("9950:SK2020317068"),
                         self.smp._sml_hostname("9950:sk2020317068"))

    def test_smp_url_comes_from_the_u_meta_smp_record(self):
        records = [
            (100, 10, "U", "Meta:other", "!.*!https://wrong.example!"),
            (100, 20, "U", "Meta:SMP", "!.*!https://second.example!"),
            (100, 10, "U", "Meta:SMP", "!^.*$!https://smp.example.sk/!"),
        ]
        self.assertEqual(self.smp._smp_url_from_naptr(records), "https://smp.example.sk")
        self.assertEqual(self.smp._smp_url_from_naptr([]), "")

    def test_doh_answers_from_cloudflare_and_google_both_parse(self):
        patch.stopall()
        for data in ('100 10 "U" "Meta:SMP" "!.*!https://sml.peppol-smp.sk!" .',
                     "100 10 U Meta:SMP !.*!https://sml.peppol-smp.sk! ."):
            answer = {"Status": 0, "Answer": [{"type": 35, "data": data}]}
            with patch("requests.get") as get:
                get.return_value.json.return_value = answer
                records = self.smp._naptr_doh("x.example")
            self.assertEqual(self.smp._smp_url_from_naptr(records),
                             "https://sml.peppol-smp.sk")
        with patch("requests.get") as get:
            get.return_value.json.return_value = {"Status": 3}
            self.assertEqual(self.smp._naptr_doh("x.example"), [])
        with patch("requests.get") as get:
            get.return_value.json.return_value = {"Status": 2}  # SERVFAIL
            with self.assertRaises(PeppolLookupError):
                self.smp._naptr_doh("x.example")

    # -- the lookup ------------------------------------------------------
    def test_a_billing_participant_is_valid(self):
        self.register("0245:2023489446",
                      (DOC_INVOICE, DOC_CREDIT_NOTE, DOC_INVOICE_RESPONSE))
        result = self.smp._lookup("0245:2023489446")
        self.assertEqual(result["state"], "valid")
        self.assertEqual(result["smp_url"], SMP)
        self.assertTrue(result["invoice_response"])

    def test_a_participant_without_credit_notes_is_not_billing(self):
        self.register("0245:2023489446", (DOC_INVOICE,))
        result = self.smp._lookup("0245:2023489446")
        self.assertEqual(result["state"], "no_billing")
        self.assertTrue(result["invoice"])
        self.assertFalse(result["credit_note"])

    def test_an_unknown_participant_is_not_registered(self):
        self.assertEqual(self.smp._lookup("0245:1234567890")["state"], "not_registered")

    def test_a_wildcard_registration_covers_bis3(self):
        self.assertTrue(EdiPeppolSmp._supports(
            ["peppol-doctype-wildcard::urn:oasis:names:specification:ubl:schema:"
             "xsd:Invoice-2::Invoice##urn:cen.eu:en16931:2017*"], DOC_INVOICE))
        self.assertFalse(EdiPeppolSmp._supports(
            ["busdox-docid-qns::" + DOC_INVOICE], DOC_CREDIT_NOTE))

    def test_an_smp_naming_someone_else_is_not_a_registration(self):
        self.network["0245:2023489446"] = service_group("0245:9999999999", (DOC_INVOICE,))
        self.assertEqual(self.smp._lookup("0245:2023489446")["state"], "not_registered")

    # -- the partner check -----------------------------------------------
    def test_check_records_the_answer_for_the_current_address(self):
        self.register("0245:2023489446")
        partner = self.partner(peppol_eas="0245", peppol_endpoint="2023489446")
        action = partner.action_peppol_smp_check()
        self.assertEqual(action["params"]["type"], "success")
        self.assertEqual(partner.peppol_smp_state, "valid")
        self.assertEqual(partner.peppol_smp_status, "valid")
        # A changed address is unchecked again.
        partner.peppol_endpoint = "2023489447"
        self.assertFalse(partner.peppol_smp_status)

    def test_a_contact_inherits_its_companys_answer(self):
        self.register("0245:2023489446")
        company = self.partner(peppol_eas="0245", peppol_endpoint="2023489446")
        person = self.env["res.partner"].create({
            "name": "Ján", "parent_id": company.id})
        person.action_peppol_smp_check()
        self.assertEqual(company.peppol_smp_state, "valid")
        self.assertEqual(person.peppol_smp_status, "valid")

    def test_a_wrong_scheme_is_corrected_from_the_vat_number(self):
        # Most Slovak participants register under the DIČ (0245), not the
        # IČ DPH (9950) Odoo derives from the VAT number.
        self.register("0245:2023489446")
        partner = self.partner(vat="SK2023489446", peppol_eas="9950",
                               peppol_endpoint="SK2023489446")
        action = partner.action_peppol_smp_check()
        self.assertEqual(self.asked, ["9950:sk2023489446", "0245:2023489446"])
        self.assertEqual((partner.peppol_eas, partner.peppol_endpoint),
                         ("0245", "2023489446"))
        self.assertEqual(partner.peppol_smp_status, "valid")
        self.assertIn("0245:2023489446", action["params"]["message"])

    def test_a_contact_without_an_address_is_found_by_vat(self):
        self.register("9950:SK2023489446")
        partner = self.partner(vat="SK2023489446")
        partner.write({"peppol_eas": False, "peppol_endpoint": False})
        partner.action_peppol_smp_check()
        self.assertEqual(self.asked, ["0245:2023489446", "9950:sk2023489446"])
        self.assertEqual((partner.peppol_eas, partner.peppol_endpoint),
                         ("9950", "SK2023489446"))

    def test_not_registered_keeps_the_address_and_says_what_was_tried(self):
        partner = self.partner(vat="SK2023489446", peppol_eas="9950",
                               peppol_endpoint="SK2023489446")
        action = partner.action_peppol_smp_check()
        self.assertEqual(action["params"]["type"], "warning")
        self.assertIn("0245:2023489446", action["params"]["message"])
        self.assertEqual(partner.peppol_eas, "9950")
        self.assertEqual(partner.peppol_smp_status, "not_registered")

    def test_nothing_to_look_up_is_a_user_error(self):
        partner = self.partner(country_id=self.env.ref("base.cz").id)
        partner.write({"peppol_eas": False, "peppol_endpoint": False})
        with self.assertRaises(UserError):
            partner.action_peppol_smp_check()

    def test_a_network_failure_is_not_not_registered(self):
        partner = self.partner(peppol_eas="0245", peppol_endpoint="2023489446")

        def broken(model, hostname):
            raise PeppolLookupError("timeout")

        with patch.object(EdiPeppolSmp, "_naptr_records", broken):
            with self.assertRaises(UserError):
                partner.action_peppol_smp_check()
        self.assertFalse(partner.peppol_smp_state)
