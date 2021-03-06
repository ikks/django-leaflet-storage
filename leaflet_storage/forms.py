import urllib2

from django import forms
from django.contrib.gis.geos import Point
from django.utils.translation import ugettext_lazy as _
from django.template.defaultfilters import slugify
from django.conf import settings

from vectorformats.formats import geojson, kml, gpx, csv

from .models import Map, DataLayer, Polyline, Polygon, Marker

DEFAULT_lATITUDE = settings.LEAFLET_LATITUDE if hasattr(settings, "LEAFLET_LATITUDE") else 51
DEFAULT_LONGITUDE = settings.LEAFLET_LONGITUDE if hasattr(settings, "LEAFLET_LONGITUDE") else 2
DEFAULT_CENTER = Point(DEFAULT_LONGITUDE, DEFAULT_lATITUDE)


class PlaceholderForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super(PlaceholderForm, self).__init__(*args, **kwargs)
        for name, field in self.fields.iteritems():
            if isinstance(field.widget, (forms.Textarea, forms.TextInput)):
                field.widget.attrs['placeholder'] = field.label
                field.label = ""


class OptionsForm(PlaceholderForm):
    """
    Manage options DictField.
    """

    PREFIX = "options_"

    def __init__(self, *args, **kwargs):
        self.options_data = {}
        self.options_names = []
        super(OptionsForm, self).__init__(*args, **kwargs)
        # Get rid of PREFIX, Leaflet.Storage expects clean form elements names
        for field_name, field in dict(self.fields).iteritems():
            if field_name.startswith(self.PREFIX):
                name = self.cut_prefix(field_name)
                self.options_names.append(name)
                del self.fields[field_name]
                self.fields[name] = field
        for option_name, value in self.instance.options.iteritems():
            if option_name in self.fields:
                self.fields[option_name].initial = value

    def cut_prefix(self, name):
        return name[len(self.PREFIX):] if name.startswith(self.PREFIX) else name

    def clean(self):
        cleaned_data = self.cleaned_data
        for field_name, value in cleaned_data.iteritems():
            if field_name in self.options_names:
                self.options_data[field_name] = value
        return cleaned_data

    def save(self, *args):
        self.instance.options = self.options_data
        return super(OptionsForm, self).save(*args)


class QuickMapCreateForm(PlaceholderForm):

    # don't bother the user with the slug and center, instead calculate them
    center = forms.CharField(required=False, widget=forms.HiddenInput())
    slug = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Map
        fields = ('name', 'description', 'licence', 'slug', 'center')

    def clean_slug(self):
        slug = self.cleaned_data.get('slug', None)
        name = self.cleaned_data.get('name', None)
        if not slug and name:
            # If name is empty, don't do nothing, validation will raise
            # later on the process because name is required
            self.cleaned_data['slug'] = slugify(name)
            return self.cleaned_data['slug'][:50]
        else:
            return ""

    def clean_center(self):
        if not self.cleaned_data['center']:
            point = DEFAULT_CENTER
            self.cleaned_data['center'] = point
        return self.cleaned_data['center']


class UpdateMapExtentForm(forms.ModelForm):

    class Meta:
        model = Map
        fields = ('zoom', 'center')


class UpdateMapTileLayerForm(forms.ModelForm):

    class Meta:
        model = Map
        fields = ('tilelayer', )


class UpdateMapPermissionsForm(forms.ModelForm):

    class Meta:
        model = Map
        fields = ('edit_status', 'editors')


class AnonymousMapPermissionsForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        super(AnonymousMapPermissionsForm, self).__init__(*args, **kwargs)
        full_secret_link = "%s%s" % (settings.SITE_URL, self.instance.get_anonymous_edit_url())
        help_text = _('Secret edit link is %s') % full_secret_link
        self.fields['edit_status'].help_text = _(help_text)

    STATUS = (
        (Map.ANONYMOUS, _('Everyone can edit')),
        (Map.OWNER, _('Only editable with secret edit link'))
    )

    edit_status = forms.ChoiceField(STATUS)

    class Meta:
        model = Map
        fields = ('edit_status', )


class UploadDataForm(forms.Form):

    GEOJSON = "geojson"
    KML = "kml"
    GPX = "gpx"
    CSV = "csv"
    CONTENT_TYPES = (
        (GEOJSON, "GeoJSON"),
        (KML, "KML"),
        (GPX, "GPX"),
        (CSV, "CSV"),
    )

    # GPX has no official content_type, so we can't guess it's type when
    # fetched from an URL which doesn't give us a file name in responses
    # headers. So for now ask user the content_type...
    content_type = forms.ChoiceField(CONTENT_TYPES, label=_("Content type"))
    data_file = forms.FileField(required=False, label=_("file"))
    data_url = forms.URLField(
        required=False,
        label=_("URL"),
        help_text=_("Supported values that will dynamically replaced: ") +
                    "{bbox}, {lat}, {lng}, {zoom}, {east}, {north}..., {left}, {top}..."
    )
    data_raw = forms.CharField(
        required=False,
        label=_("Copy/paste"),
        widget=forms.Textarea
    )
    datalayer = forms.ModelChoiceField([], label=_("datalayer"))  # queryset is set by view

    def clean_data_file(self):
        """
        Return a features list if file is valid.
        Otherwise raise a ValidationError.
        """
        features = []
        f = self.cleaned_data.get('data_file')
        if f:
            features = self.content_to_features(f.read())
        return features

    def clean_data_url(self):
        url = self.cleaned_data.get('data_url')
        features = []
        if url:
            try:
                response = urllib2.urlopen(url)
            except urllib2.URLError:
                raise forms.ValidationError(_('Unable to fetch content from URL.'))
            else:
                content = response.read()
                features = self.content_to_features(content)
        return features

    def clean_data_raw(self):
        data = self.cleaned_data.get('data_raw')
        features = []
        if data:
            features = self.content_to_features(data)
        return features

    def clean(self):
        cleaned_data = super(UploadDataForm, self).clean()
        data_file = cleaned_data.get("data_file")
        data_url = cleaned_data.get("data_url")
        data_raw = cleaned_data.get("data_raw")
        data_sources = [data_file, data_url, data_raw]
        if sum((bool(s) for s in data_sources)) != 1 and not self.errors:
            raise forms.ValidationError(_("You must provide one data source."))
        return cleaned_data

    def content_to_features(self, content):
        features = []
        content_type = self.cleaned_data.get('content_type')
        MAP = {
            self.GEOJSON: geojson.GeoJSON,
            self.KML: kml.KML,
            self.GPX: gpx.GPX,
            self.CSV: csv.CSV,
        }
        if not content_type in MAP:
            raise forms.ValidationError(_('Unsupported content_type: %s') % content_type)
        format = MAP[content_type]()
        try:
            features = format.decode(content)
        except Exception, e:
            msg = _('Invalid %(content_type)s') % {'content_type': content_type}
            msg = u"%s (Detail: %s)" % (msg, e)
            raise forms.ValidationError(msg)
        return features


class DownloadDataForm(forms.Form):

    GEOJSON = "geojson"
    CONTENT_TYPES = (
        (GEOJSON, "GeoJSON"),
    )

    content_type = forms.ChoiceField(CONTENT_TYPES, label=_("Format"))


class PathStyleMixin(forms.ModelForm):
    options_smoothFactor = forms.FloatField(
        required=False,
        label=_('Path smooth factor'),
        help_text=_("How much to simplify the polyline on each zoom level "
                    "(more = better performance and smoother look, less = more accurate)")
    )
    options_opacity = forms.FloatField(
        required=False,
        min_value=0.1,
        max_value=10,
        label=_('Path opacity'),
        help_text=_("Opacity, from 0.1 to 1.0 (opaque).")
    )
    options_stroke = forms.BooleanField(
        required=False,
        initial=True,
        label=_('Polygon stroke'),
        help_text=_("Whether to display or not the Polygon path.")
    )
    options_weight = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=10,
        label=_('Path weight'),
        help_text=_("Path weight in pixels. Max: 10.")
    )
    options_fill = forms.BooleanField(
        required=False,
        initial=True,
        label=_('Path fill'),
        help_text=_("Whether to fill the path with color.")
    )
    options_fillOpacity = forms.FloatField(
        required=False,
        min_value=0.1,
        max_value=10,
        label=_('Fill opacity'),
        help_text=_("Fill opacity, from 0.1 to 1.0 (opaque).")
    )
    options_fillColor = forms.CharField(
        required=False,
        label=_('Fill color'),
        help_text=_("Optional. Same as color if not set.")
    )
    options_dashArray = forms.CharField(
        required=False,
        label=_('Dash array'),
        help_text=_("A string that defines the stroke dash pattern. Ex.: '5, 10, 15'.")
    )


class DataLayerForm(OptionsForm, PathStyleMixin):

    options_color = forms.CharField(
        required=False,
        label=_('color'),
        help_text=_("Must be a CSS valid name (eg.: DarkBlue or #123456)")
    )

    class Meta:
        model = DataLayer
        widgets = {
            "map": forms.HiddenInput(),
            "icon_class": forms.HiddenInput(),
            "pictogram": forms.HiddenInput()
        }


class FeatureForm(OptionsForm):

    options_color = forms.CharField(
        required=False,
        label=_('color'),
        help_text=_("Optional. Layer color is used if not set.")
    )


class PolygonForm(FeatureForm, PathStyleMixin):

    class Meta:
        model = Polygon
        fields = ('name', 'description', 'datalayer', 'latlng')
        widgets = {
            'latlng': forms.HiddenInput(),
        }


class PolylineForm(FeatureForm, PathStyleMixin):

    def __init__(self, *args, **kwargs):
        super(PolylineForm, self).__init__(*args, **kwargs)
        self.fields["fill"].initial = False

    class Meta:
        fields = ('name', 'description', 'datalayer', 'latlng')
        model = Polyline
        widgets = {
            'latlng': forms.HiddenInput(),
        }


class MarkerForm(FeatureForm):

    class Meta:
        fields = ('name', 'description', 'datalayer', 'latlng', 'icon_class', 'pictogram')
        model = Marker
        widgets = {
            'latlng': forms.HiddenInput(),
            "icon_class": forms.HiddenInput(),
            "pictogram": forms.HiddenInput()
        }


class MapSettingsForm(forms.Form):

    SETTINGS = (
        # name, help_text, default
        ("locateControl", _("Do you want to display the locate control?"), True),
        ("jumpToLocationControl", _("Do you want to display the 'quick search' control?"), True),
        ("homeControl", _("Do you want to display the 'back to home page' control?"), True),
        ("embedControl", _("Do you want to display the embed control?"), True),
        ("scaleControl", _("Do you want to display the scale control?"), True),
        ("locateOnLoad", _("Do you want to locate user on load?"), False),
        ("tileLayersControl", _("Do you want to display a tilelayer switcher?"), True),
        ("displayCaptionOnLoad", _("Do you want to display map caption on load?"), False),
        ("displayDataBrowserOnLoad", _("Do you want to display data browser on load?"), False),
        ("displayPopupFooter", _("Do you want to display popup footer?"), False),
        ("miniMap", _("Do you want to display a minimap?"), False),
        ("scrollWheelZoom", _("Allow scroll wheel zoom?"), True),
        ("editInOSMControl", _("Do you want to display control with links to edit in OSM?"), False),
        ("enableMarkerDraw", _("Do you want to enable Marker drawing?"), True),
        ("enablePolylineDraw", _("Do you want to enable Polyline drawing?"), True),
        ("enablePolygonDraw", _("Do you want to enable Polygon drawing?"), True),
    )

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.pop('instance')
        super(MapSettingsForm, self).__init__(*args, **kwargs)
        for name, help_text, default in self.SETTINGS:
            attrs = {
                "required": False,
                "help_text": help_text,
                "initial": self.instance.settings[name] if name in self.instance.settings else default
            }
            self.fields[name] = forms.BooleanField(**attrs)
