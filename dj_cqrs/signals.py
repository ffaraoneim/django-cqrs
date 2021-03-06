#  Copyright © 2020 Ingram Micro Inc. All rights reserved.

from django.db import models, transaction
from django.dispatch import Signal
from django.utils.timezone import now

from dj_cqrs.controller import producer
from dj_cqrs.constants import SignalType
from dj_cqrs.dataclasses import TransportPayload

post_bulk_create = Signal(providing_args=['instances', 'using'])
post_update = Signal(providing_args=['instances', 'using'])


class MasterSignals:
    """ Signals registry and handlers for CQRS master models. """
    @classmethod
    def register_model(cls, model_cls):
        """
        :param dj_cqrs.mixins.MasterMixin model_cls: Class inherited from CQRS MasterMixin.
        """
        models.signals.post_save.connect(cls.post_save, sender=model_cls)
        models.signals.post_delete.connect(cls.post_delete, sender=model_cls)

        post_bulk_create.connect(cls.post_bulk_create, sender=model_cls)
        post_update.connect(cls.post_bulk_update, sender=model_cls)

    @classmethod
    def post_save(cls, sender, **kwargs):
        """
        :param dj_cqrs.mixins.MasterMixin sender: Class or instance inherited from CQRS MasterMixin.
        """
        if not sender.CQRS_PRODUCE:
            return

        instance = kwargs['instance']
        if not instance.is_sync_instance():
            return

        using = kwargs['using']

        sync = kwargs.get('sync', False)
        queue = kwargs.get('queue', None)

        if not transaction.get_connection(using).in_atomic_block:
            instance_data = instance.to_cqrs_dict(using)

            signal_type = SignalType.SYNC if sync else SignalType.SAVE
            payload = TransportPayload(
                signal_type, sender.CQRS_ID, instance_data, instance.pk, queue,
            )
            producer.produce(payload)

        else:
            transaction.on_commit(
                lambda: MasterSignals.post_save(
                    sender, instance=instance, using=using, sync=sync, queue=queue,
                ),
            )

    @classmethod
    def post_delete(cls, sender, **kwargs):
        """
        :param dj_cqrs.mixins.MasterMixin sender: Class or instance inherited from CQRS MasterMixin.
        """
        if not sender.CQRS_PRODUCE:
            return

        instance = kwargs['instance']
        if not instance.is_sync_instance():
            return

        instance_data = {
            'id': instance.pk,
            'cqrs_revision': instance.cqrs_revision + 1,
            'cqrs_updated': str(now()),
        }
        signal_type = SignalType.DELETE

        payload = TransportPayload(signal_type, sender.CQRS_ID, instance_data, instance.pk)
        # Delete is always in transaction!
        transaction.on_commit(lambda: producer.produce(payload))

    @classmethod
    def post_bulk_create(cls, sender, **kwargs):
        """
        :param dj_cqrs.mixins.MasterMixin sender: Class or instance inherited from CQRS MasterMixin.
        """
        for instance in kwargs['instances']:
            cls.post_save(sender, instance=instance, using=kwargs['using'])

    @classmethod
    def post_bulk_update(cls, sender, **kwargs):
        """
        :param dj_cqrs.mixins.MasterMixin sender: Class or instance inherited from CQRS MasterMixin.
        """
        for instance in kwargs['instances']:
            cls.post_save(sender, instance=instance, using=kwargs['using'])
