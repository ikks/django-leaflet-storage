from django.contrib.auth.models import AnonymousUser

from leaflet_storage.models import Marker, Map, DataLayer
from .base import BaseTest, UserFactory, MarkerFactory, DataLayerFactory,\
                  PolygonFactory, PolylineFactory


class MapModel(BaseTest):

    def test_anonymous_can_edit_if_status_anonymous(self):
        anonymous = AnonymousUser()
        self.map.edit_status = self.map.ANONYMOUS
        self.map.save()
        self.assertTrue(self.map.can_edit(anonymous))

    def test_anonymous_cannot_edit_if_not_status_anonymous(self):
        anonymous = AnonymousUser()
        self.map.edit_status = self.map.OWNER
        self.map.save()
        self.assertFalse(self.map.can_edit(anonymous))

    def test_non_editors_can_edit_if_status_anonymous(self):
        lambda_user = UserFactory(username="John", password="123123")
        self.map.edit_status = self.map.ANONYMOUS
        self.map.save()
        self.assertTrue(self.map.can_edit(lambda_user))

    def test_non_editors_cannot_edit_if_not_status_anonymous(self):
        lambda_user = UserFactory(username="John", password="123123")
        self.map.edit_status = self.map.OWNER
        self.map.save()
        self.assertFalse(self.map.can_edit(lambda_user))

    def test_editors_cannot_edit_if_status_owner(self):
        editor = UserFactory(username="John", password="123123")
        self.map.edit_status = self.map.OWNER
        self.map.save()
        self.assertFalse(self.map.can_edit(editor))

    def test_editors_can_edit_if_status_editors(self):
        editor = UserFactory(username="John", password="123123")
        self.map.edit_status = self.map.EDITORS
        self.map.editors.add(editor)
        self.map.save()
        self.assertTrue(self.map.can_edit(editor))


class LicenceModel(BaseTest):

    def test_licence_delete_should_not_remove_linked_maps(self):
        marker = MarkerFactory(datalayer=self.datalayer)
        self.assertEqual(marker.datalayer.map.licence, self.licence)
        self.licence.delete()
        self.assertEqual(Map.objects.filter(pk=self.map.pk).count(), 1)
        self.assertEqual(DataLayer.objects.filter(pk=self.datalayer.pk).count(), 1)
        self.assertEqual(Marker.objects.filter(pk=marker.pk).count(), 1)


class DataLayerModel(BaseTest):

    def test_features_should_be_locally_cached(self):
        MarkerFactory(datalayer=self.datalayer)
        MarkerFactory(datalayer=self.datalayer)
        MarkerFactory(datalayer=self.datalayer)
        self.datalayer.features
        with self.assertNumQueries(0):
            self.datalayer.features

    def test_datalayers_should_be_ordered_by_name(self):
        c4 = DataLayerFactory(map=self.map, name="eeeeeee")
        c1 = DataLayerFactory(map=self.map, name="1111111")
        c3 = DataLayerFactory(map=self.map, name="ccccccc")
        c2 = DataLayerFactory(map=self.map, name="aaaaaaa")
        self.assertEqual(
            list(self.map.datalayer_set.all()),
            [c1, c2, c3, c4, self.datalayer]
        )

    def test_features_should_be_mixed_and_ordered_by_name(self):
        f4 = MarkerFactory(datalayer=self.datalayer, name="eeee")
        f1 = PolygonFactory(datalayer=self.datalayer, name="1111")
        f3 = PolylineFactory(datalayer=self.datalayer, name="cccc")
        f2 = MarkerFactory(datalayer=self.datalayer, name="aaaa")
        self.assertEqual(
            list(self.datalayer.features),
            [f1, f2, f3, f4]
        )
