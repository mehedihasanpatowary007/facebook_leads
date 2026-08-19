/**
 * Portal Timesheet Submit - Fixed JSON loading
 */
(function () {
    'use strict';

    // Read from script tags (t-raw ensures unescaped JSON)
    function readJSON(id) {
        var el = document.getElementById(id);
        if (!el) {
            console.error('Portal TS: Element not found:', id);
            return [];
        }
        try {
            // Get the raw text content
            var content = el.textContent || el.innerHTML || '[]';
            // Clean any whitespace
            content = content.trim();
            console.log('Portal TS: Raw content from', id, ':', content.substring(0, 200));
            var data = JSON.parse(content);
            console.log('Portal TS: Parsed', data.length, 'items from', id);
            return data;
        } catch (e) {
            console.error('Portal TS: Failed to parse JSON from', id, e);
            console.error('Content was:', el.textContent);
            return [];
        }
    }

    function parseTime(raw) {
        var s = (raw || '').trim();
        if (!s) return NaN;
        if (s.indexOf(':') !== -1) {
            var p = s.split(':');
            if (p.length !== 2) return NaN;
            var h = parseInt(p[0], 10), m = parseInt(p[1], 10);
            if (isNaN(h) || isNaN(m) || m < 0 || m > 59) return NaN;
            return h + m / 60;
        }
        var n = parseFloat(s);
        return isNaN(n) ? NaN : n;
    }

    function fmtHours(h) {
        var hh = Math.floor(h), mm = Math.round((h - hh) * 60);
        return String(hh).padStart(2, '0') + ':' + String(mm).padStart(2, '0');
    }

    function fmtDate(iso) {
        if (!iso) return '';
        try {
            return new Date(iso + 'T00:00:00').toLocaleDateString(undefined, {
                year: 'numeric', month: 'short', day: 'numeric'
            });
        } catch (e) { return iso; }
    }

    function esc(s) {
        return String(s || '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function setOptions(sel, items, placeholder) {
        sel.innerHTML = '';
        var blank = document.createElement('option');
        blank.value = '';
        blank.textContent = placeholder;
        sel.appendChild(blank);
        (items || []).forEach(function (it) {
            var o = document.createElement('option');
            o.value = it.id;
            o.textContent = it.name;
            sel.appendChild(o);
        });
    }

    // ── Main ──────────────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {

        var modal = document.getElementById('portalTimesheetModal');
        if (!modal) {
            console.error('Portal TS: Modal not found');
            return;
        }

        // Read data from script tags
        var PROJECTS = readJSON('portal_ts_projects');
        var TASKS = readJSON('portal_ts_tasks');
        
        console.log('Portal TS: Total projects loaded:', PROJECTS.length);
        console.log('Portal TS: Total tasks loaded:', TASKS.length);
        
        // Log first few items for debugging
        if (PROJECTS.length > 0) {
            console.log('Portal TS: First project:', PROJECTS[0]);
        }
        if (TASKS.length > 0) {
            console.log('Portal TS: First task:', TASKS[0]);
        }

        var selProject = document.getElementById('portal_ts_project');
        var selTask    = document.getElementById('portal_ts_task');
        var inpDate    = document.getElementById('portal_ts_date');
        var inpTime    = document.getElementById('portal_ts_time');
        var inpDesc    = document.getElementById('portal_ts_desc');
        var btnSave    = document.getElementById('portal_ts_save');
        var spinner    = document.getElementById('portal_ts_spinner');
        var saveIcon   = document.getElementById('portal_ts_save_icon');
        var errBox     = document.getElementById('portal_ts_error');
        var errTxt     = document.getElementById('portal_ts_error_msg');

        var today = new Date().toISOString().split('T')[0];

        function showErr(msg) {
            errTxt.textContent = msg;
            errBox.classList.remove('d-none');
            errBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        
        function hideErr() {
            errBox.classList.add('d-none');
            errTxt.textContent = '';
        }
        
        function setBusy(on) {
            btnSave.disabled = on;
            spinner.classList.toggle('d-none', !on);
            saveIcon.classList.toggle('d-none', on);
        }

        // ── Modal open: populate Project dropdown ─────────────────────────────
        modal.addEventListener('show.bs.modal', function () {
            hideErr();
            inpDate.value = today;
            inpTime.value = '';
            inpDesc.value = '';
            [selProject, inpDate, inpTime].forEach(function (el) {
                el.classList.remove('is-invalid');
            });

            console.log('Portal TS: Modal opening, projects available:', PROJECTS.length);

            if (PROJECTS.length === 0) {
                setOptions(selProject, [], 'No projects assigned to you');
                showErr('No projects found. Please ask your administrator to assign you to a project via "Assign Portal Users".');
                btnSave.disabled = true;
            } else {
                setOptions(selProject, PROJECTS, '-- Select a project --');
                btnSave.disabled = false;
                console.log('Portal TS: Project dropdown populated with', PROJECTS.length, 'items');
            }

            // Reset task dropdown
            setOptions(selTask, [], '-- Select a task (optional) --');
            selTask.disabled = true;
        });

        // ── Project change: filter tasks by project_id ────────────────────────
        selProject.addEventListener('change', function () {
            var pid = parseInt(selProject.value, 10);
            console.log('Portal TS: Project changed to ID:', pid);

            if (!pid) {
                setOptions(selTask, [], '-- Select a task (optional) --');
                selTask.disabled = true;
                return;
            }

            // Filter tasks for this project
            var filtered = TASKS.filter(function (t) {
                return t.project_id === pid;
            });
            
            console.log('Portal TS: Found', filtered.length, 'tasks for project', pid);

            if (!filtered.length) {
                setOptions(selTask, [], 'No tasks assigned to you in this project');
                selTask.disabled = true;
            } else {
                setOptions(selTask, filtered, '-- Select a task (optional) --');
                selTask.disabled = false;
            }
        });

        // ── Save: POST to /my/timesheets/submit → account.analytic.line ───────
        btnSave.addEventListener('click', function () {
            hideErr();
            var valid = true;

            if (!selProject.value) {
                selProject.classList.add('is-invalid');
                valid = false;
            } else {
                selProject.classList.remove('is-invalid');
            }

            if (!inpDate.value) {
                inpDate.classList.add('is-invalid');
                valid = false;
            } else {
                inpDate.classList.remove('is-invalid');
            }

            var hours = parseTime(inpTime.value);
            if (isNaN(hours) || hours <= 0) {
                inpTime.classList.add('is-invalid');
                valid = false;
            } else {
                inpTime.classList.remove('is-invalid');
            }

            if (!valid) {
                showErr('Please fill in all required fields correctly.');
                return;
            }

            setBusy(true);

            fetch('/my/timesheets/submit', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_id:  parseInt(selProject.value, 10),
                    task_id:     selTask.value ? parseInt(selTask.value, 10) : null,
                    name:        inpDesc.value.trim(),
                    entry_date:  inpDate.value,
                    unit_amount: hours,
                }),
            })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                setBusy(false);
                if (!res.success) {
                    showErr(res.error || 'An error occurred. Please try again.');
                    return;
                }
                
                var bsModal = (typeof bootstrap !== 'undefined') &&
                              bootstrap.Modal.getInstance(modal);
                if (bsModal) bsModal.hide();
                
                insertRow(res);
            })
            .catch(function (err) {
                setBusy(false);
                showErr('Network error: ' + err.message);
            });
        });

        // ── Inject new row into table after successful submit ─────────────────
        function insertRow(r) {
            var tbody = document.querySelector(
                '.o_portal_my_doc_table tbody, ' +
                '.o_portal_wrap table tbody, ' +
                'table.table tbody'
            );
            if (!tbody) {
                window.location.reload();
                return;
            }
            var tr = document.createElement('tr');
            tr.className = 'portal_ts_new_row';
            tr.innerHTML =
                '<td>' + esc(fmtDate(r.date)) + '</td>' +
                '<td>' + esc(r.project_name || '—') + '</td>' +
                '<td>' + esc(r.task_name    || '—') + '</td>' +
                '<td>' + esc(r.description  || '—') + '</td>' +
                '<td class="text-end">' + esc(fmtHours(r.unit_amount || 0)) + '</td>';
            tbody.insertBefore(tr, tbody.firstChild);
        }

    });

}());