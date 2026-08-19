# -*- coding: utf-8 -*-
"""
Portal Timesheet Submit Controller — v13 with Task Assignee Filtering
======================================================================
Key Change: Internal users now also only see tasks where they are assigned (user_ids).
"""

import json
import logging
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from operator import itemgetter

from odoo import fields, http, _
from odoo.fields import Domain
from odoo.http import request, Response
from odoo.tools import date_utils, groupby as groupbyelem
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.addons.hr_timesheet.controllers.portal import TimesheetCustomerPortal

_logger = logging.getLogger(__name__)


def _json_resp(data):
    return Response(
        json.dumps(data, ensure_ascii=False),
        status=200,
        mimetype='application/json',
    )


def _get_employee(user):
    """Get employee record linked to user"""
    employee = request.env['hr.employee'].sudo().search(
        [('user_id', '=', user.id)], limit=1
    )
    if not employee:
        employee = request.env['hr.employee'].sudo().search(
            [('work_contact_id', '=', user.partner_id.id)], limit=1
        )
    return employee


def _is_internal(user):
    return user.has_group('base.group_user')


def _get_portal_user_projects(user):
    """
    Return only projects the portal user is actually assigned to:
      - Projects where the user is listed in portal_user_ids (direct project assignment), OR
      - Projects that contain tasks the user is assigned to via user_ids.

    Internal users continue to see all active timesheet-enabled projects.
    The old "last resort" fallback to all projects has been removed — a user
    with no assignments should see nothing, not everything.
    """
    Project = request.env['project.project'].sudo()

    if _is_internal(user):
        projects = Project.search(
            [('active', '=', True), ('allow_timesheets', '=', True)],
            order='name asc',
        )
        _logger.info(f"Internal user {user.name}: Found {len(projects)} projects")
        return projects

    # Branch A: directly assigned to project via portal_user_ids
    portal_assigned = Project.search([
        ('portal_user_ids', 'in', user.id),
        ('active', '=', True),
        ('allow_timesheets', '=', True),
    ])

    # Branch B: assigned to a task inside a project via user_ids
    task_projects = (
        request.env['project.task'].sudo()
        .search([('user_ids', 'in', user.id), ('project_id', '!=', False)])
        .mapped('project_id')
        .filtered(lambda p: p.active and p.allow_timesheets)
    )

    # Union of both (no duplicates)
    all_projects = portal_assigned | task_projects
    _logger.info(
        f"Portal user {user.name}: {len(portal_assigned)} via portal_user_ids, "
        f"{len(task_projects)} via tasks → {len(all_projects)} total"
    )
    return all_projects


def _get_portal_user_tasks(user, project_ids=None):
    """
    Get tasks where the user is assigned (user_ids).
    IMPORTANT: This now filters by assignee for BOTH internal AND portal users.
    """
    if not project_ids:
        return request.env['project.task'].sudo().browse([])
    
    domain = [
        ('project_id', 'in', project_ids),
        ('stage_id.fold', '=', False),
        # KEY CHANGE: Filter by assignee for ALL users (internal + portal)
        ('user_ids', 'in', user.id),
    ]
    
    tasks = request.env['project.task'].sudo().search(
        domain, order='project_id asc, name asc'
    )
    _logger.info(f"User {user.name}: Found {len(tasks)} assigned tasks for projects {project_ids}")
    return tasks


class PortalTimesheetSubmit(TimesheetCustomerPortal):
    """
    Enhanced portal timesheet controller with proper assignment filtering.
    """

    # --------------------------------------------------------------------
    # PORTAL HOME: show the "Timesheets" card even with zero entries
    # --------------------------------------------------------------------

    def _prepare_home_portal_values(self, counters):
        """
        Override to make the "Timesheets" card appear on the portal home page
        as soon as the user is assigned to at least one project or task —
        regardless of whether any timesheet entries exist yet.

        WHY THIS IS NEEDED
        ------------------
        The base implementation (TimesheetCustomerPortal) calls:

            values['timesheet_count'] = Timesheet.sudo().search_count(domain)

        where `domain` comes from _timesheet_get_portal_domain().  Even with
        our fixed domain (assignment-based instead of follower-based), if the
        user has zero timesheet entries the count is still 0.

        Odoo's portal home template uses `portal_docs_entry` which hides the
        card entirely when the placeholder count is 0.  So a freshly-assigned
        portal user — who has no timesheets yet but should be able to submit
        them — sees no "Timesheets" card and has no obvious entry point.

        FIX
        ---
        When `timesheet_count` is requested:
          1. Run the normal domain search for actual timesheet records.
          2. If the count is already > 0, use it as-is (real count shown).
          3. If the count is 0, check whether the user has at least one
             accessible project (via task assignment or portal_user_ids).
             If yes, return 1 so the card renders — the list page itself will
             show "There are no timesheets" with the New Entry button visible.
        """
        values = super()._prepare_home_portal_values(counters)

        if 'timesheet_count' in counters:
            if not values.get('timesheet_count'):
                # No existing timesheets — check assignment instead.
                user = request.env.user
                accessible_projects = _get_portal_user_projects(user)
                if accessible_projects:
                    # Force the card to appear.  The actual count shown in the
                    # card will be 0; the list page has the New Entry button.
                    values['timesheet_count'] = 1

        return values

    # --------------------------------------------------------------------
    # SEARCH ROUTES (AJAX endpoints for dropdowns)
    # --------------------------------------------------------------------
    
    @http.route(
        '/my/timesheets/search/projects',
        type='json',
        auth='user',
        website=True,
        methods=['POST']
    )
    def search_projects(self, **kw):
        """Search projects for dropdown"""
        try:
            user = request.env.user
            search_term = kw.get('search_term', '').strip()
            
            accessible_projects = _get_portal_user_projects(user)
            
            if search_term:
                accessible_projects = accessible_projects.filtered(
                    lambda p: search_term.lower() in (p.name or '').lower()
                )
            
            projects = accessible_projects[:20]
            
            results = []
            for project in projects:
                results.append({
                    'id': project.id,
                    'name': project.name,
                    'type': 'Project'
                })
            
            _logger.info(f"Project search for user {user.name}: '{search_term}' → {len(results)} results")
            return {'items': results}
            
        except Exception as e:
            _logger.error(f"Error in project search: {str(e)}", exc_info=True)
            return {'items': [], 'error': str(e)}
    
    @http.route(
        '/my/timesheets/search/tasks',
        type='json',
        auth='user',
        website=True,
        methods=['POST']
    )
    def search_tasks(self, **kw):
        """Search tasks for dropdown - filtered by project AND user assignment"""
        try:
            user = request.env.user
            search_term = kw.get('search_term', '').strip()
            project_id = kw.get('project_id')
            
            # Get tasks accessible to user (already filtered by user_ids)
            if project_id:
                try:
                    project_id = int(project_id)
                    tasks = _get_portal_user_tasks(user, [project_id])
                except (ValueError, TypeError):
                    tasks = request.env['project.task'].sudo().browse([])
            else:
                # Get all projects first, then tasks
                projects = _get_portal_user_projects(user)
                tasks = _get_portal_user_tasks(user, projects.ids) if projects else request.env['project.task'].sudo().browse([])
            
            if search_term:
                tasks = tasks.filtered(
                    lambda t: search_term.lower() in (t.name or '').lower()
                )
            
            tasks = tasks[:20]
            
            results = []
            for task in tasks:
                results.append({
                    'id': task.id,
                    'name': task.name,
                    'project_id': task.project_id.id,
                    'project_name': task.project_id.name,
                    'type': 'Task'
                })
            
            _logger.info(f"Task search for user {user.name}: project={project_id}, term='{search_term}' → {len(results)} results")
            return {'items': results}
            
        except Exception as e:
            _logger.error(f"Error in task search: {str(e)}", exc_info=True)
            return {'items': [], 'error': str(e)}

    # --------------------------------------------------------------------
    # PAGE ROUTES
    # --------------------------------------------------------------------

    @http.route(
        ['/my/timesheets', '/my/timesheets/page/<int:page>'],
        type='http',
        auth='user',
        website=True,
    )
    def portal_my_timesheets(self, page=1, sortby=None, filterby=None,
                              search=None, search_in='all', groupby='none', **kw):
        """
        Timesheet list page.
        """
        Timesheet = request.env['account.analytic.line']
        domain = Domain(Timesheet._timesheet_get_portal_domain())
        Timesheet_sudo = Timesheet.sudo()

        values = self._prepare_portal_layout_values()
        items_per_page = 100

        searchbar_sortings = self._get_searchbar_sortings()
        searchbar_inputs = dict(sorted(
            self._get_searchbar_inputs().items(),
            key=lambda item: item[1]['sequence']
        ))
        searchbar_groupby = dict(sorted(
            self._get_searchbar_groupby().items(),
            key=lambda item: item[1]['sequence']
        ))

        today = fields.Date.today()
        quarter_start, quarter_end = date_utils.get_quarter(today)
        last_quarter_date = date_utils.subtract(quarter_start, weeks=1)
        last_quarter_start, last_quarter_end = date_utils.get_quarter(last_quarter_date)
        last_week = today + relativedelta(weeks=-1)
        last_month = today + relativedelta(months=-1)
        last_year = today + relativedelta(years=-1)

        searchbar_filters = {
            'all': {'label': _('All'), 'domain': []},
            'last_year': {'label': _('Last Year'), 'domain': [
                ('date', '>=', date_utils.start_of(last_year, 'year')),
                ('date', '<=', date_utils.end_of(last_year, 'year'))
            ]},
            'last_quarter': {'label': _('Last Quarter'), 'domain': [
                ('date', '>=', last_quarter_start),
                ('date', '<=', last_quarter_end)
            ]},
            'last_month': {'label': _('Last Month'), 'domain': [
                ('date', '>=', date_utils.start_of(last_month, 'month')),
                ('date', '<=', date_utils.end_of(last_month, 'month'))
            ]},
            'last_week': {'label': _('Last Week'), 'domain': [
                ('date', '>=', date_utils.start_of(last_week, 'week')),
                ('date', '<=', date_utils.end_of(last_week, 'week'))
            ]},
            'today': {'label': _('Today'), 'domain': [('date', '=', today)]},
            'week': {'label': _('This Week'), 'domain': [
                ('date', '>=', date_utils.start_of(today, 'week')),
                ('date', '<=', date_utils.end_of(today, 'week'))
            ]},
            'month': {'label': _('This Month'), 'domain': [
                ('date', '>=', date_utils.start_of(today, 'month')),
                ('date', '<=', date_utils.end_of(today, 'month'))
            ]},
            'quarter': {'label': _('This Quarter'), 'domain': [
                ('date', '>=', quarter_start),
                ('date', '<=', quarter_end)
            ]},
            'year': {'label': _('This Year'), 'domain': [
                ('date', '>=', date_utils.start_of(today, 'year')),
                ('date', '<=', date_utils.end_of(today, 'year'))
            ]},
        }

        if not sortby:
            sortby = 'date desc'
        if not filterby:
            filterby = 'all'

        domain &= Domain(searchbar_filters[filterby]['domain'])

        if search and search_in:
            domain &= self._get_search_domain(search_in, search)

        if parent_task_id := kw.get('parent_task_id'):
            domain &= Domain('parent_task_id', '=', int(parent_task_id))

        timesheet_count = Timesheet_sudo.search_count(domain)

        pager = portal_pager(
            url='/my/timesheets',
            url_args={
                'sortby': sortby, 'search_in': search_in,
                'search': search, 'filterby': filterby, 'groupby': groupby,
            },
            total=timesheet_count,
            page=page,
            step=items_per_page,
        )

        def get_timesheets():
            field = None if groupby == 'none' else groupby
            orderby = '%s, %s' % (field, sortby) if field else sortby
            timesheets = Timesheet_sudo.search(
                domain, order=orderby,
                limit=items_per_page, offset=pager['offset']
            )
            if field:
                if groupby == 'date':
                    raw = Timesheet_sudo._read_group(
                        domain, ['date:day'],
                        ['unit_amount:sum', 'id:recordset'],
                        order='date:day desc',
                    )
                    grouped = [(records, ua) for __, ua, records in raw]
                else:
                    time_data = Timesheet_sudo._read_group(domain, [field], ['unit_amount:sum'])
                    mapped_time = {f.id: ua for f, ua in time_data}
                    grouped = [
                        (Timesheet_sudo.concat(*g), mapped_time[k.id])
                        for k, g in groupbyelem(timesheets, itemgetter(field))
                    ]
                return timesheets, grouped

            grouped = [(
                timesheets,
                Timesheet_sudo._read_group(domain, aggregates=['unit_amount:sum'])[0][0]
            )] if timesheets else []
            return timesheets, grouped

        timesheets, grouped_timesheets = get_timesheets()

        values.update({
            'timesheets': timesheets,
            'grouped_timesheets': grouped_timesheets,
            'page_name': 'timesheet',
            'default_url': '/my/timesheets',
            'pager': pager,
            'searchbar_sortings': searchbar_sortings,
            'search_in': search_in,
            'search': search,
            'sortby': sortby,
            'groupby': groupby,
            'searchbar_inputs': searchbar_inputs,
            'searchbar_groupby': searchbar_groupby,
            'searchbar_filters': searchbar_filters,
            'filterby': filterby,
            'is_uom_day': Timesheet._is_timesheet_encode_uom_day(),
        })

        return request.render('hr_timesheet.portal_my_timesheets', values)

    @http.route(
        '/my/timesheets/create',
        type='http',
        auth='user',
        website=True,
    )
    def portal_timesheet_create_form(self, **kw):
        """
        Display the timesheet creation form page.
        """
        user = request.env.user
        
        # Get current user's employee record
        employee = _get_employee(user)
        
        # Get today's date for the form
        today = fields.Date.today().strftime('%Y-%m-%d')
        
        _logger.info(f"Timesheet create form for user {user.name}")
        
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'timesheet_create',
            'default_url': '/my/timesheets',
            'employee': employee,
            'today': today,
        })
        
        return request.render('portal_timesheet_submit.timesheet_create_form', values)

    @http.route(
        '/my/timesheets/submit',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=False,
        website=True,
    )
    def submit_timesheet(self, **kw):
        """
        Create a new timesheet entry with proper validation.
        """
        try:
            user = request.env.user

            ct = (request.httprequest.content_type or '').lower()
            if 'application/json' in ct:
                body = request.httprequest.get_json(force=True, silent=True) or {}
            else:
                body = kw

            project_id = body.get('project_id')
            task_id = body.get('task_id')
            name = body.get('name', '') or ''
            entry_date = body.get('entry_date', '')
            unit_amount = body.get('unit_amount', 0)

            # Validate project_id
            if not project_id:
                return _json_resp({'success': False, 'error': 'Project is required.'})
            try:
                project_id = int(project_id)
            except (ValueError, TypeError):
                return _json_resp({'success': False, 'error': 'Invalid project.'})

            # Verify user has access to this project
            accessible_projects = _get_portal_user_projects(user)
            if project_id not in accessible_projects.ids:
                return _json_resp({
                    'success': False,
                    'error': 'You do not have access to this project.'
                })

            project = request.env['project.project'].sudo().browse(project_id)
            if not project.exists():
                return _json_resp({'success': False, 'error': 'Project not found.'})

            # Validate task_id (optional but must be accessible if provided)
            task = None
            if task_id:
                try:
                    task_id = int(task_id)
                except (ValueError, TypeError):
                    return _json_resp({'success': False, 'error': 'Invalid task.'})
                
                task = request.env['project.task'].sudo().browse(task_id)
                if not task.exists():
                    return _json_resp({'success': False, 'error': 'Task not found.'})
                
                if task.project_id.id != project_id:
                    return _json_resp({
                        'success': False,
                        'error': 'Task does not belong to the selected project.'
                    })
                
                # KEY CHANGE: Verify user is assigned to this task (for BOTH internal and portal users)
                if user.id not in task.user_ids.ids:
                    return _json_resp({
                        'success': False,
                        'error': 'You are not assigned to this task.'
                    })

            # Validate unit_amount
            try:
                unit_amount = float(unit_amount)
            except (ValueError, TypeError):
                return _json_resp({'success': False, 'error': 'Invalid time value.'})
            if unit_amount <= 0:
                return _json_resp({
                    'success': False,
                    'error': 'Time spent must be greater than zero.'
                })
            if unit_amount > 24:
                return _json_resp({
                    'success': False,
                    'error': 'Time spent cannot exceed 24 hours per entry.'
                })

            # Validate date
            if entry_date:
                try:
                    parsed_date = datetime.strptime(str(entry_date), '%Y-%m-%d').date()
                except ValueError:
                    return _json_resp({'success': False, 'error': 'Invalid date format.'})
            else:
                parsed_date = date.today()

            # Get employee record for the user
            employee = _get_employee(user)
            if not employee:
                return _json_resp({
                    'success': False,
                    'error': (
                        'No Employee record is linked to your account. '
                        'Please contact your administrator.'
                    )
                })

            # Create timesheet entry
            vals = {
                'project_id': project_id,
                'task_id': task.id if task else False,
                'name': name.strip() or '/',
                'date': fields.Date.to_string(parsed_date),
                'unit_amount': unit_amount,
                'employee_id': employee.id,
                'user_id': user.id,
            }

            new_line = request.env['account.analytic.line'].sudo().create(vals)

            _logger.info(
                'Portal timesheet created | user=%s employee=%s line=%s '
                'project="%s" task="%s" hours=%.2f date=%s',
                user.login, employee.name, new_line.id,
                project.name, task.name if task else '-',
                unit_amount, parsed_date,
            )

            return _json_resp({
                'success': True,
                'id': new_line.id,
                'date': fields.Date.to_string(parsed_date),
                'project_name': project.name,
                'task_name': task.name if task else '',
                'description': new_line.name,
                'unit_amount': unit_amount,
            })

        except (AccessError, ValidationError) as exc:
            _logger.warning('Portal timesheet validation error: %s', exc)
            return _json_resp({'success': False, 'error': str(exc)})
        except Exception:
            _logger.error('Portal timesheet unexpected error', exc_info=True)
            return _json_resp({
                'success': False,
                'error': 'An unexpected error occurred. Please try again.'
            })

    @http.route(
        '/my/timesheets/debug',
        type='http',
        auth='user',
        website=True,
    )
    def debug_timesheet_data(self, **kw):
        """Debug endpoint to check what data is available"""
        user = request.env.user
        
        Project = request.env['project.project'].sudo()
        field_exists = 'portal_user_ids' in Project._fields
        
        all_projects = Project.search([
            ('active', '=', True), 
            ('allow_timesheets', '=', True)
        ])
        
        portal_assigned = Project.search([
            ('portal_user_ids', 'in', user.id),
            ('active', '=', True),
            ('allow_timesheets', '=', True),
        ])
        
        assigned_tasks = request.env['project.task'].sudo().search([
            ('user_ids', 'in', user.id),
        ])
        
        debug_info = {
            'user': {
                'id': user.id,
                'name': user.name,
                'login': user.login,
                'is_internal': _is_internal(user),
                'share': user.share,
            },
            'field_exists': field_exists,
            'all_projects_count': len(all_projects),
            'all_projects': [{'id': p.id, 'name': p.name} for p in all_projects[:5]],
            'portal_assigned_count': len(portal_assigned),
            'portal_assigned': [{'id': p.id, 'name': p.name} for p in portal_assigned],
            'assigned_tasks_count': len(assigned_tasks),
            'assigned_tasks': [{'id': t.id, 'name': t.name, 'project_id': t.project_id.id} for t in assigned_tasks[:5]],
        }
        
        return _json_resp(debug_info)