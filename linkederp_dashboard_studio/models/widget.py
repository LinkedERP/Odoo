import ast
import logging
from datetime import date, datetime

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.osv import expression


_logger = logging.getLogger(__name__)

NUMERIC_FIELD_TYPES = ("integer", "float", "monetary")
GROUPABLE_FIELD_TYPES = (
    "boolean",
    "char",
    "date",
    "datetime",
    "many2one",
    "selection",
)
DATE_INTERVALS = ("day", "week", "month", "quarter", "year")


class LinkederpDashboardWidget(models.Model):
    _name = "linkederp.dashboard.widget"
    _description = "LinkedERP Dashboard Widget"
    _order = "dashboard_id, sequence, name"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    dashboard_id = fields.Many2one(
        "linkederp.dashboard",
        required=True,
        ondelete="cascade",
    )
    widget_type = fields.Selection(
        [
            ("kpi", "KPI"),
            ("bar", "Bar Chart"),
            ("line", "Line Chart"),
            ("pie", "Pie Chart"),
            ("table", "Table"),
        ],
        required=True,
        default="kpi",
    )
    model_id = fields.Many2one(
        "ir.model",
        required=True,
        ondelete="cascade",
        domain=[("transient", "=", False)],
    )
    model_name = fields.Char(related="model_id.model", store=True, readonly=True)
    value_mode = fields.Selection(
        [
            ("count", "Count"),
            ("sum", "Sum"),
            ("avg", "Average"),
        ],
        default="count",
        required=True,
    )
    measure_field_id = fields.Many2one(
        "ir.model.fields",
        string="Measure Field",
        domain=[
            ("ttype", "in", NUMERIC_FIELD_TYPES),
            ("store", "=", True),
        ],
    )
    groupby_field_id = fields.Many2one(
        "ir.model.fields",
        string="Group By Field",
        domain=[
            ("ttype", "in", GROUPABLE_FIELD_TYPES),
            ("store", "=", True),
        ],
    )
    groupby_interval = fields.Selection(
        [
            ("day", "Day"),
            ("week", "Week"),
            ("month", "Month"),
            ("quarter", "Quarter"),
            ("year", "Year"),
        ],
        default="month",
        help="Used only when the group-by field is a date or datetime field.",
    )
    date_field_id = fields.Many2one(
        "ir.model.fields",
        string="Dashboard Date Filter",
        domain=[
            ("ttype", "in", ("date", "datetime")),
            ("store", "=", True),
        ],
        help="Optional field used by the global date filter.",
    )
    domain_filter = fields.Char(
        default="[]",
        help="Odoo domain applied before dashboard filters, for example [('state', '=', 'sale')].",
    )
    limit = fields.Integer(default=8)
    color = fields.Char(default="#2563eb")
    help_text = fields.Char(translate=True)

    @api.onchange("model_id")
    def _onchange_model_id(self):
        self.measure_field_id = False
        self.groupby_field_id = False
        self.date_field_id = False

    @api.constrains("value_mode", "measure_field_id", "widget_type", "groupby_field_id", "limit")
    def _check_widget_configuration(self):
        for widget in self:
            if widget.value_mode != "count" and not widget.measure_field_id:
                raise ValidationError(_("A measure field is required for sum and average widgets."))
            if widget.widget_type in ("bar", "line", "pie", "table") and not widget.groupby_field_id:
                raise ValidationError(_("A group-by field is required for chart and table widgets."))
            if widget.limit < 1:
                raise ValidationError(_("Widget limit must be greater than zero."))

    @api.constrains("model_id", "measure_field_id", "groupby_field_id", "date_field_id")
    def _check_fields_match_model(self):
        for widget in self:
            model = widget.model_id
            for field in (
                widget.measure_field_id,
                widget.groupby_field_id,
                widget.date_field_id,
            ):
                if field and field.model_id != model:
                    raise ValidationError(_("Widget fields must belong to the selected model."))

    def _get_payload(self, date_from=False, date_to=False, extra_domain=False):
        self.ensure_one()
        try:
            payload = self._build_payload(date_from=date_from, date_to=date_to, extra_domain=extra_domain)
        except AccessError:
            payload = self._error_payload(_("Not enough access to read this data."))
        except Exception as error:
            _logger.exception("Unable to render dashboard widget %s", self.id)
            payload = self._error_payload(str(error))
        return payload

    def _build_payload(self, date_from=False, date_to=False, extra_domain=False):
        model = self._target_model()
        domain = self._date_filtered_domain(
            date_from=date_from,
            date_to=date_to,
            extra_domain=extra_domain,
        )

        if self.widget_type == "kpi":
            value = self._read_total(model, domain)
            points = []
        else:
            points = self._read_grouped_points(model, domain)
            value = sum(point["value"] for point in points)

        return {
            "id": self.id,
            "name": self.name,
            "type": self.widget_type,
            "model": self.model_name,
            "mode": self.value_mode,
            "measure": self.measure_field_id.field_description
            if self.measure_field_id
            else _("Records"),
            "groupby": self.groupby_field_id.field_description
            if self.groupby_field_id
            else "",
            "color": self.color or "#2563eb",
            "help": self.help_text or "",
            "value": self._number(value),
            "format": "number",
            "domain": self._json_safe(domain),
            "points": points,
            "error": False,
        }

    def _error_payload(self, message):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.widget_type,
            "model": self.model_name,
            "mode": self.value_mode,
            "measure": self.measure_field_id.field_description
            if self.measure_field_id
            else _("Records"),
            "groupby": self.groupby_field_id.field_description
            if self.groupby_field_id
            else "",
            "color": self.color or "#dc2626",
            "help": self.help_text or "",
            "value": 0,
            "format": "number",
            "domain": [],
            "points": [],
            "error": message,
        }

    def _target_model(self):
        if not self.model_name or self.model_name not in self.env:
            raise UserError(_("Model %s is not available.") % (self.model_name or ""))
        model = self.env[self.model_name]
        model.check_access_rights("read")
        return model

    def _base_domain(self):
        if not self.domain_filter:
            return []
        domain = ast.literal_eval(self.domain_filter)
        if not isinstance(domain, list):
            raise UserError(_("Widget domain must be a valid Odoo domain list."))
        return domain

    def _date_filtered_domain(self, date_from=False, date_to=False, extra_domain=False):
        domain = self._base_domain()
        date_field = self.date_field_id.name if self.date_field_id else False
        date_domain = []
        if date_field and date_from:
            date_domain.append((date_field, ">=", date_from))
        if date_field and date_to:
            date_domain.append((date_field, "<=", date_to))
        if extra_domain:
            date_domain = expression.AND([date_domain, extra_domain]) if date_domain else extra_domain
        if date_domain:
            return expression.AND([domain, date_domain])
        return domain

    def _read_total(self, model, domain):
        if self.value_mode == "count":
            return model.search_count(domain)

        result = model.read_group(
            domain,
            [self._measure_read_group_field()],
            [],
            lazy=False,
        )
        return result and self._extract_measure(result[0]) or 0

    def _read_grouped_points(self, model, domain):
        groupby = self._groupby_read_group_field()
        fields_to_read = [self.groupby_field_id.name]
        if self.value_mode != "count":
            fields_to_read.append(self._measure_read_group_field())

        buckets = model.read_group(
            domain,
            fields_to_read,
            [groupby],
            limit=self.limit,
            lazy=False,
        )

        points = []
        for bucket in buckets:
            value = bucket.get("__count", 0) if self.value_mode == "count" else self._extract_measure(bucket)
            points.append(
                {
                    "label": self._bucket_label(bucket, groupby),
                    "value": self._number(value),
                    "domain": self._json_safe(bucket.get("__domain", domain)),
                }
            )

        if self.groupby_field_id.ttype in ("date", "datetime"):
            return points
        return sorted(points, key=lambda point: point["value"], reverse=True)

    def _measure_read_group_field(self):
        return "%s:%s" % (self.measure_field_id.name, self.value_mode)

    def _groupby_read_group_field(self):
        field_name = self.groupby_field_id.name
        if self.groupby_field_id.ttype in ("date", "datetime") and self.groupby_interval in DATE_INTERVALS:
            return "%s:%s" % (field_name, self.groupby_interval)
        return field_name

    def _bucket_label(self, bucket, groupby):
        field_name = self.groupby_field_id.name
        value = bucket.get(field_name, bucket.get(groupby))
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return value[1] or _("Undefined")
        if value in (False, None, ""):
            return _("Undefined")
        return str(value)

    def _extract_measure(self, bucket):
        field_name = self.measure_field_id.name
        for key in (field_name, "%s_%s" % (field_name, self.value_mode), self._measure_read_group_field()):
            if key in bucket:
                return bucket[key] or 0
        for key, value in bucket.items():
            if key.startswith(field_name) and isinstance(value, (int, float)):
                return value
        return 0

    def _number(self, value):
        return float(value or 0)

    def _json_safe(self, value):
        if isinstance(value, datetime):
            return fields.Datetime.to_string(value)
        if isinstance(value, date):
            return fields.Date.to_string(value)
        if isinstance(value, tuple):
            return [self._json_safe(item) for item in value]
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        if isinstance(value, dict):
            return {key: self._json_safe(item) for key, item in value.items()}
        return value
