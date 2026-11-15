import os
import csv
import json
import uuid
import re
import threading
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ALL_APPS_JSON = os.path.join(DATA_DIR, "all_applications.json")
ALL_APPS_CSV = os.path.join(DATA_DIR, "all_applications.csv")

VALID_STATUSES = [
    "Applied",
    "Screening / Assessment",
    "HR Screening Call",
    "Interview Scheduled",
    "Offer",
    "Rejected",
    "On Hold"
]

STATUS_PRIORITY = {
    "Applied": 1,
    "Screening / Assessment": 2,
    "HR Screening Call": 3,
    "Interview Scheduled": 4,
    "Offer": 5,
    "On Hold": 1,
    "Rejected": 1
}

class ApplicationTracker:
    def __init__(self, data_dir=DATA_DIR):
        self.data_dir = data_dir
        self.json_path = os.path.join(data_dir, "all_applications.json")
        self.csv_path = os.path.join(data_dir, "all_applications.csv")
        self.lock = threading.RLock()
        self._ensure_files()

    def _ensure_files(self):
        os.makedirs(self.data_dir, exist_ok=True)
        if not os.path.exists(self.json_path):
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)

    def _read_apps(self) -> list:
        with self.lock:
            try:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    apps = json.load(f)
                    return [a for a in apps if a.get("company", "").strip().lower() not in ["unknown company", "unknown", ""]]
            except Exception:
                return []

    def _write_apps(self, apps: list):
        with self.lock:
            # Sort newest first
            apps.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(apps, f, indent=2, ensure_ascii=False)
            self._sync_to_csv(apps)

    def _sync_to_csv(self, apps: list):
        try:
            fields = [
                "id", "timestamp", "company", "role", "source", "status",
                "recruiter_name", "recruiter_contact", "job_url", "notes", "last_updated"
            ]
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                for app in apps:
                    writer.writerow(app)
        except Exception as e:
            print(f"[Tracker] Error exporting CSV: {e}")

    def get_all(self, status=None, source=None, search=None) -> list:
        apps = self._read_apps()
        if status and status.lower() != "all":
            apps = [a for a in apps if a.get("status", "").lower() == status.lower()]
        if source and source.lower() != "all":
            apps = [a for a in apps if a.get("source", "").lower() == source.lower()]
        if search:
            q = search.lower().strip()
            apps = [
                a for a in apps
                if q in a.get("company", "").lower()
                or q in a.get("role", "").lower()
                or q in a.get("recruiter_name", "").lower()
                or q in a.get("notes", "").lower()
            ]
        return apps

    def get_stats(self) -> dict:
        apps = self._read_apps()
        counts = {
            "total": len(apps),
            "applied": 0,
            "screening": 0,
            "hr_screening": 0,
            "interview": 0,
            "offer": 0,
            "rejected": 0,
            "on_hold": 0,
            "sources": {}
        }
        for a in apps:
            st = a.get("status", "Applied")
            if st == "Applied":
                counts["applied"] += 1
            elif "Screening" in st or "Assessment" in st:
                counts["screening"] += 1
            elif "HR" in st:
                counts["hr_screening"] += 1
            elif "Interview" in st:
                counts["interview"] += 1
            elif st == "Offer":
                counts["offer"] += 1
            elif st == "Rejected":
                counts["rejected"] += 1
            elif st == "On Hold":
                counts["on_hold"] += 1
            else:
                counts["applied"] += 1

            src = a.get("source", "Other")
            counts["sources"][src] = counts["sources"].get(src, 0) + 1

        return counts

    def add_application(self, company: str, role: str, source: str = "Manual / Recruiter Call",
                        status: str = "Applied", recruiter_name: str = "", recruiter_contact: str = "",
                        job_url: str = "", notes: str = "", timestamp: str = None) -> dict:
        with self.lock:
            apps = self._read_apps()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            app_id = f"app_{uuid.uuid4().hex[:8]}"

            new_record = {
                "id": app_id,
                "timestamp": timestamp or now_str,
                "company": (company or "Unknown Company").strip(),
                "role": (role or "Job Applicant").strip(),
                "source": source or "Manual / Recruiter Call",
                "status": status if status in VALID_STATUSES else "Applied",
                "recruiter_name": recruiter_name.strip(),
                "recruiter_contact": recruiter_contact.strip(),
                "job_url": job_url.strip(),
                "notes": notes.strip(),
                "history": [
                    {
                        "timestamp": now_str,
                        "status": status,
                        "note": notes or f"Entry created via {source}"
                    }
                ],
                "last_updated": now_str
            }
            apps.append(new_record)
            self._write_apps(apps)
            return new_record

    def update_application(self, app_id: str, status: str = None, notes: str = None,
                           recruiter_name: str = None, recruiter_contact: str = None,
                           role: str = None, company: str = None) -> dict:
        with self.lock:
            apps = self._read_apps()
            target = None
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for a in apps:
                if a.get("id") == app_id:
                    target = a
                    break

            if not target:
                return None

            status_changed = False
            old_status = target.get("status")

            if status and status in VALID_STATUSES and status != old_status:
                target["status"] = status
                status_changed = True

            if notes is not None:
                target["notes"] = notes

            if recruiter_name is not None:
                target["recruiter_name"] = recruiter_name

            if recruiter_contact is not None:
                target["recruiter_contact"] = recruiter_contact

            if role is not None:
                target["role"] = role

            if company is not None:
                target["company"] = company

            target["last_updated"] = now_str

            if "history" not in target:
                target["history"] = []

            if status_changed:
                target["history"].append({
                    "timestamp": now_str,
                    "status": target["status"],
                    "note": f"Status updated from '{old_status}' to '{target['status']}'" + (f": {notes}" if notes else "")
                })
            elif notes and not status_changed:
                target["history"].append({
                    "timestamp": now_str,
                    "status": target["status"],
                    "note": f"Notes updated: {notes}"
                })

            self._write_apps(apps)
            return target

    def delete_application(self, app_id: str) -> bool:
        with self.lock:
            apps = self._read_apps()
            initial_len = len(apps)
            apps = [a for a in apps if a.get("id") != app_id]
            if len(apps) != initial_len:
                self._write_apps(apps)
                return True
            return False

    def sync_all_sources(self) -> dict:
        """
        Synchronizes applications from:
        1. data/naukri_applied_jobs.csv
        2. data/easy_apply_jobs.json
        3. data/manual_applications.csv
        4. data/screening_passed_opportunities.json
        5. data/email_applications_tracker.json
        6. data/email_intelligence.json
        Does NOT downgrade manually updated statuses.
        """
        with self.lock:
            apps = self._read_apps()
            # Map by normalized key: (clean_company, clean_role)
            existing_map = {}
            for a in apps:
                key = (
                    re.sub(r"[^a-zA-Z0-9]", "", a.get("company", "").lower()),
                    re.sub(r"[^a-zA-Z0-9]", "", a.get("role", "").lower())[:15]
                )
                existing_map[key] = a

            imported_naukri = 0
            imported_easy = 0
            imported_manual = 0
            email_promoted = 0
            email_direct_created = 0

            # 1. Ingest Naukri Applied Jobs
            naukri_csv = os.path.join(self.data_dir, "naukri_applied_jobs.csv")
            if os.path.exists(naukri_csv):
                try:
                    with open(naukri_csv, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for r in reader:
                            comp = r.get("company", "").strip()
                            role = r.get("title", "").strip()
                            if not comp or not role or comp.lower() in ["unknown company", "unknown"]:
                                continue
                            norm_key = (
                                re.sub(r"[^a-zA-Z0-9]", "", comp.lower()),
                                re.sub(r"[^a-zA-Z0-9]", "", role.lower())[:15]
                            )
                            if norm_key not in existing_map:
                                new_rec = {
                                    "id": f"app_{uuid.uuid4().hex[:8]}",
                                    "timestamp": r.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "company": comp,
                                    "role": role,
                                    "source": "Naukri",
                                    "status": "Applied",
                                    "recruiter_name": "",
                                    "recruiter_contact": "",
                                    "job_url": r.get("job_url", ""),
                                    "notes": f"Applied via Naukri Autopilot ({r.get('location', '')})",
                                    "history": [
                                        {
                                            "timestamp": r.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                            "status": "Applied",
                                            "note": "Applied via Naukri Autopilot"
                                        }
                                    ],
                                    "last_updated": r.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                }
                                apps.append(new_rec)
                                existing_map[norm_key] = new_rec
                                imported_naukri += 1
                except Exception as e:
                    print(f"[Tracker] Error reading Naukri CSV: {e}")

            # 2. Ingest Easy Apply Jobs
            easy_json = os.path.join(self.data_dir, "easy_apply_jobs.json")
            if os.path.exists(easy_json):
                try:
                    with open(easy_json, "r", encoding="utf-8") as f:
                        easy_list = json.load(f)
                        for r in easy_list:
                            comp = r.get("company", "").strip()
                            role = r.get("title", "").strip()
                            if not comp or not role or comp.lower() in ["unknown company", "unknown"]:
                                continue
                            norm_key = (
                                re.sub(r"[^a-zA-Z0-9]", "", comp.lower()),
                                re.sub(r"[^a-zA-Z0-9]", "", role.lower())[:15]
                            )
                            if norm_key not in existing_map:
                                new_rec = {
                                    "id": f"app_{uuid.uuid4().hex[:8]}",
                                    "timestamp": r.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "company": comp,
                                    "role": role,
                                    "source": "LinkedIn Easy Apply",
                                    "status": "Applied",
                                    "recruiter_name": "",
                                    "recruiter_contact": "",
                                    "job_url": r.get("job_url", ""),
                                    "notes": f"Easy Apply listing ({r.get('location', '')})",
                                    "history": [
                                        {
                                            "timestamp": r.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                            "status": "Applied",
                                            "note": "LinkedIn Easy Apply Submission"
                                        }
                                    ],
                                    "last_updated": r.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                }
                                apps.append(new_rec)
                                existing_map[norm_key] = new_rec
                                imported_easy += 1
                except Exception as e:
                    print(f"[Tracker] Error reading Easy Apply JSON: {e}")

            # 3. Ingest Manual/External Applications
            man_csv = os.path.join(self.data_dir, "manual_applications.csv")
            if os.path.exists(man_csv):
                try:
                    with open(man_csv, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for r in reader:
                            comp = r.get("company", "").strip()
                            role = r.get("title", "").strip()
                            if not comp or not role or comp.lower() in ["unknown company", "unknown"]:
                                continue
                            norm_key = (
                                re.sub(r"[^a-zA-Z0-9]", "", comp.lower()),
                                re.sub(r"[^a-zA-Z0-9]", "", role.lower())[:15]
                            )
                            if norm_key not in existing_map:
                                direct_url = r.get("direct_application_url") or r.get("job_url", "")
                                new_rec = {
                                    "id": f"app_{uuid.uuid4().hex[:8]}",
                                    "timestamp": r.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "company": comp,
                                    "role": role,
                                    "source": "Direct Portal",
                                    "status": "Applied",
                                    "recruiter_name": "",
                                    "recruiter_contact": "",
                                    "job_url": direct_url,
                                    "notes": r.get("reason", "Direct Portal Application"),
                                    "history": [
                                        {
                                            "timestamp": r.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                            "status": "Applied",
                                            "note": "Direct Application Portal Submission"
                                        }
                                    ],
                                    "last_updated": r.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                }
                                apps.append(new_rec)
                                existing_map[norm_key] = new_rec
                                imported_manual += 1
                except Exception as e:
                    print(f"[Tracker] Error reading Manual Applications CSV: {e}")

            # 4. Ingest & Correlate Email Intelligence
            email_files = [
                os.path.join(self.data_dir, "screening_passed_opportunities.json"),
                os.path.join(self.data_dir, "email_applications_tracker.json"),
                os.path.join(self.data_dir, "email_intelligence.json")
            ]

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for ef in email_files:
                if not os.path.exists(ef):
                    continue
                try:
                    with open(ef, "r", encoding="utf-8") as f:
                        emails = json.load(f)
                        if not isinstance(emails, list):
                            continue
                        for em in emails:
                            comp = (em.get("company") or "").strip()
                            subj = em.get("subject", "")
                            snip = em.get("snippet", "")
                            sender = em.get("sender", "")
                            cat = em.get("category", "")
                            next_act = em.get("next_action") or em.get("next_step", "")

                            # Determine status from email contents
                            inferred_status = "Applied"
                            combined_text = f"{subj} {snip} {cat} {next_act}".lower()

                            if any(k in combined_text for k in ["interview", "discussion", "shortlist", "round 1", "round 2", "telephonic interview"]):
                                inferred_status = "Interview Scheduled"
                            elif any(k in combined_text for k in ["test", "assessment", "cbt", "admit card", "exam", "coding challenge", "hackerrank", "screening passed"]):
                                inferred_status = "Screening / Assessment"
                            elif any(k in combined_text for k in ["call", "hr", "recruiter screening", "talent acquisition", "spoken"]):
                                inferred_status = "HR Screening Call"
                            elif any(k in combined_text for k in ["offer", "selection", "congratulations"]):
                                inferred_status = "Offer"
                            elif any(k in combined_text for k in ["unfortunately", "not moving forward", "regret to inform"]):
                                inferred_status = "Rejected"

                            # Match against existing application companies
                            matched_app = None
                            comp_clean = re.sub(r"[^a-zA-Z0-9]", "", comp.lower())
                            if comp_clean and comp_clean not in ["naukri", "linkedin", "naukrilisting"]:
                                for a in apps:
                                    a_comp_clean = re.sub(r"[^a-zA-Z0-9]", "", a.get("company", "").lower())
                                    if a_comp_clean and (a_comp_clean in comp_clean or comp_clean in a_comp_clean):
                                        matched_app = a
                                        break

                            if matched_app:
                                # Promote status if higher priority and not previously set higher
                                cur_prio = STATUS_PRIORITY.get(matched_app.get("status", "Applied"), 1)
                                new_prio = STATUS_PRIORITY.get(inferred_status, 1)

                                note_addition = f"Email Intel: {subj} ({next_act or snip[:80]})"
                                if new_prio > cur_prio:
                                    old_st = matched_app.get("status")
                                    matched_app["status"] = inferred_status
                                    matched_app["notes"] = f"{matched_app.get('notes', '')} | {note_addition}".strip(" |")
                                    matched_app["last_updated"] = now_str
                                    matched_app.setdefault("history", []).append({
                                        "timestamp": now_str,
                                        "status": inferred_status,
                                        "note": f"Promoted via Email Intelligence from '{old_st}' to '{inferred_status}': {subj}"
                                    })
                                    email_promoted += 1
                                elif note_addition not in matched_app.get("notes", ""):
                                    matched_app["notes"] = f"{matched_app.get('notes', '')} | {note_addition}".strip(" |")
                                    matched_app["last_updated"] = now_str
                            else:
                                # Direct application or outreach not seen in Naukri / Easy Apply
                                if comp and comp.lower() not in ["naukri", "linkedin", "naukri listing"]:
                                    norm_key = (
                                        comp_clean,
                                        "direct"
                                    )
                                    if norm_key not in existing_map:
                                        # Extract role from subject if possible
                                        role_match = re.search(r"(?:for|role of|position of|as)\s+([A-Za-z0-9\s\-/]+?)(?:\sat|\son|\swith|$)", subj, re.I)
                                        inferred_role = role_match.group(1).strip() if role_match else "Role via Direct Outreach"

                                        new_rec = {
                                            "id": f"app_{uuid.uuid4().hex[:8]}",
                                            "timestamp": em.get("timestamp") or em.get("date") or now_str,
                                            "company": comp,
                                            "role": inferred_role,
                                            "source": "Recruiter Email / Direct",
                                            "status": inferred_status,
                                            "recruiter_name": sender,
                                            "recruiter_contact": em.get("gmail_link", ""),
                                            "job_url": em.get("gmail_link", ""),
                                            "notes": f"Captured from Email: {subj} - {snip}",
                                            "history": [
                                                {
                                                    "timestamp": now_str,
                                                    "status": inferred_status,
                                                    "note": f"Direct recruitment detected from email ({subj})"
                                                }
                                            ],
                                            "last_updated": now_str
                                        }
                                        apps.append(new_rec)
                                        existing_map[norm_key] = new_rec
                                        email_direct_created += 1
                except Exception as e:
                    print(f"[Tracker] Error processing email file {ef}: {e}")

            self._write_apps(apps)
            return {
                "total_applications": len(apps),
                "imported_naukri": imported_naukri,
                "imported_easy_apply": imported_easy,
                "imported_manual": imported_manual,
                "email_promoted": email_promoted,
                "email_direct_created": email_direct_created
            }

tracker = ApplicationTracker()
