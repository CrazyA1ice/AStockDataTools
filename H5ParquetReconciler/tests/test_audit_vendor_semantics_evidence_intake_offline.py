"""Only synthetic documents and synthetic SAFE reports; no market source."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location(
    "standalone_vendor_semantic_intake_test",
    HERE.parent/"tools"/"audit-vendor-semantics-evidence-intake-offline.py")
A=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


def footer_fixture():
    roles={name:0 for name in A.KNOWN_METADATA_ROLES}
    return {
        "format":A.FOOTER_FORMAT,
        "status":"purchased_day_footer_metadata_presence_only_not_vendor_unit_attestation",
        "source_files_footer_only_read":24,
        "row_groups_footer_only_scanned":139,
        "parquet_footer_only_no_market_rows_read":True,
        "purchased_day_file_set_and_stat_unchanged":True,
        "purchased_day_original_modified":False,
        "source_vendor_data_dictionary_attached_and_verified":False,
        "historical_physical_price_volume_amount_units_certified":False,
        "historical_adjustment_and_securities_certified":False,
        "ready_to_normalize_historical_raw_or_write_h5_mirror":False,
        "metadata_candidate_role_field_occurrences":roles,
        "metadata_candidate_role_table_occurrences":dict(roles),
    }


@contextmanager
def setup():
    with tempfile.TemporaryDirectory() as dirname:
        root=Path(dirname)
        reports=root/"reports"
        evidence=root/"work"/"vendor_semantics"
        reports.mkdir()
        evidence.mkdir(parents=True)
        prior=reports/"purchased-original-footer.json"
        prior.write_text(json.dumps(footer_fixture()),encoding="utf-8")
        dest=reports/"vendor-intake-safe.json"
        with (patch.object(A,"MODULE",root),
              patch.object(A,"REPORTS",reports),
              patch.object(A,"EVIDENCE",evidence)):
            yield root,prior,dest,evidence


def fill_evidence(evidence,role_status="all",bad_sha=False):
    doc=evidence/"purchased-batch-2026.pdf"
    doc.write_bytes(b"PRIVATE SELLER CONTRACT. price unit currency share or unit 2026")
    sha=hashlib.sha256(doc.read_bytes()).hexdigest()
    loci={role:{"status":"documented","section_locator":"PRIVATE SECTION 2"}
          for role in A.ROLES}
    if role_status=="partial":
        loci[A.ROLES[-1]]={"status":"unknown","section_locator":""}
    if role_status=="none":
        loci={role:{"status":"unknown","section_locator":""}
              for role in A.ROLES}
    notes={
        "format":"private_vendor_semantics_source_loci_v1",
        "document_filename":doc.name,
        "document_sha256":("f"*64 if bad_sha else sha),
        "product_version_reference":"PRIVATE PRODUCT ID batch 2026",
        "purchase_batch_reference":"PRIVATE RECEIPT / DATE",
        "role_loci":loci,
    }
    path=evidence/"private-vendor-source-notes.json"
    path.write_text(json.dumps(notes),encoding="utf-8")
    return path,doc


class VendorSemanticsEvidenceIntakeTests(unittest.TestCase):
    def test_plan_all_unknown_only_reads_prior_footer_safe(self):
        with setup() as (_root,prior,out,_evidence):
            result=A.audit("plan",prior,out)
            self.assertEqual(result["status"],"blocked_missing_vendor_semantics_source")
            self.assertEqual(result["required_semantic_roles_total"],len(A.ROLES))
            self.assertEqual(result["undocumented_required_role_names"],list(A.ROLES))
            self.assertFalse(result["private_vendor_document_supplied"])
            self.assertFalse(result["historical_normalized_parquet_authorized"])
            self.assertFalse(result["hikyuu_h5_mirror_authorized"])
            self.assertFalse(result["original_purchased_parquet_or_h5_accessed"])
            self.assertTrue(out.is_file())

    def test_intake_all_claimed_sections_still_never_certifies_units(self):
        with setup() as (_root,prior,out,evidence):
            notes,doc=fill_evidence(evidence)
            previous={p:p.read_bytes() for p in (prior,notes,doc)}
            result=A.audit("intake",prior,out,notes)
            self.assertTrue(result["private_vendor_document_supplied"])
            self.assertEqual(len(result["documented_source_section_role_names_only"]),
                             len(A.ROLES))
            self.assertEqual(result["undocumented_required_role_names"],[])
            for k in ("independent_document_authenticity_checked",
                      "document_claims_independently_verified",
                      "purchased_vendor_physical_units_certified",
                      "historical_volume_amount_rounding_certified",
                      "historical_adjustment_basis_certified",
                      "historical_security_master_certified",
                      "historical_normalized_parquet_authorized",
                      "hikyuu_h5_mirror_authorized",
                      "original_purchased_parquet_or_h5_accessed",
                      "raw_vendor_document_or_claim_values_exported"):
                self.assertIs(result[k],False,k)
            safe=out.read_text(encoding="utf-8")
            for secret in ("PRIVATE SELLER","PRIVATE SECTION","PRIVATE PRODUCT",
                           "PRIVATE RECEIPT","purchased-batch-2026.pdf"):
                self.assertNotIn(secret,safe)
            self.assertEqual(previous,{p:p.read_bytes() for p in previous})

    def test_partial_document_section_locations_return_missing_roles(self):
        with setup() as (_root,prior,out,evidence):
            notes,_=fill_evidence(evidence,"partial")
            result=A.audit("intake",prior,out,notes)
            self.assertEqual(result["undocumented_required_role_names"],
                             [A.ROLES[-1]])
            self.assertEqual(len(result["documented_source_section_role_names_only"]),
                             len(A.ROLES)-1)

    def test_sham_certificate_flags_from_vendor_notes_never_enable_write(self):
        with setup() as (_root,prior,out,evidence):
            notes,_=fill_evidence(evidence)
            obj=json.loads(notes.read_text(encoding="utf-8"))
            obj["certified"]=True
            notes.write_text(json.dumps(obj),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"format invalid"):
                A.audit("intake",prior,out,notes)
            self.assertFalse(out.exists())
        for arbitrary in (None,{},{"certified":True},
                          {"historical_normalized_parquet_authorized":True}):
            with self.assertRaises(PermissionError):
                A.require_normalization_authorization(arbitrary)

    def test_tampered_vendor_document_sha_rejected(self):
        with setup() as (_root,prior,out,evidence):
            notes,doc=fill_evidence(evidence)
            doc.write_bytes(doc.read_bytes()+b"\nAFTER CERTIFICATION")
            with self.assertRaisesRegex(ValueError,"SHA"):
                A.audit("intake",prior,out,notes)
            self.assertFalse(out.exists())

    def test_missing_evidence_rejected_and_plan_with_notes_forbidden(self):
        with setup() as (_root,prior,out,evidence):
            with self.assertRaisesRegex(ValueError,"requires"):
                A.audit("intake",prior,out)
            with self.assertRaisesRegex(ValueError,"PLAN"):
                A.audit("plan",prior,out,evidence/"no.json")
            notes,doc=fill_evidence(evidence)
            doc.unlink()
            with self.assertRaises(ValueError):
                A.audit("intake",prior,out,notes)
            self.assertFalse(out.exists())

    def test_prior_footer_safe_claiming_certification_must_be_rejected(self):
        with setup() as (_root,prior,out,evidence):
            obj=footer_fixture()
            obj["historical_physical_price_volume_amount_units_certified"]=True
            prior.write_text(json.dumps(obj),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"uncertified"):
                A.audit("plan",prior,out)
            self.assertFalse(out.exists())

    def test_prior_footer_role_structure_must_be_exact(self):
        with setup() as (_root,prior,out,evidence):
            obj=footer_fixture()
            del obj["metadata_candidate_role_field_occurrences"]["amount_unit"]
            prior.write_text(json.dumps(obj),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"structure"):
                A.audit("plan",prior,out)
            self.assertFalse(out.exists())

    def test_existing_safe_output_never_overwritten(self):
        with setup() as (_root,prior,out,_evidence):
            out.write_bytes(b"THIS REPORT IS PROTECTED")
            with self.assertRaisesRegex(ValueError,"never overwrite"):
                A.audit("plan",prior,out)
            self.assertEqual(out.read_bytes(),b"THIS REPORT IS PROTECTED")

    def test_unqualified_document_paths_and_notes_are_rejected(self):
        with setup() as (root,prior,out,evidence):
            notes,doc=fill_evidence(evidence)
            n=json.loads(notes.read_text(encoding="utf-8"))
            n["document_filename"]="../../private-2026.pdf"
            notes.write_text(json.dumps(n),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"private filename"):
                A.audit("intake",prior,out,notes)
            self.assertFalse(out.exists())
            n["document_filename"]=doc.name
            n["role_loci"][A.ROLES[0]]["section_locator"]=""
            notes.write_text(json.dumps(n),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"section"):
                A.audit("intake",prior,out,notes)
            self.assertFalse(out.exists())

    def test_document_size_budget_and_disabled_market_read_api(self):
        with setup() as (_root,prior,out,evidence):
            notes,doc=fill_evidence(evidence)
            with patch.object(A,"MAX_DOC_BYTES",16):
                with self.assertRaisesRegex(ValueError,"size budget"):
                    A.audit("intake",prior,out,notes)
            code=(HERE.parent/"tools"/
                  "audit-vendor-semantics-evidence-intake-offline.py").read_text(
                      encoding="utf-8")
            for forbidden in ("h5py.File(","pyarrow.parquet","ParquetFile(",
                              "sqlite3.connect(","os.replace(",
                              "active-day-overlay.json"):
                self.assertNotIn(forbidden,code)
            self.assertFalse(out.exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
