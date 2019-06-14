"""
Middleware for analytics app to parse the Google Analytics (GA) cookie and the LMS user_id.
"""
import logging
from edx_django_utils import monitoring as monitoring_utils
from ecommerce.extensions.analytics.utils import get_google_analytics_client_id

logger = logging.getLogger(__name__)


class TrackingMiddleware(object):
    """
    Middleware that:
        1) parses the `_ga` cookie to find the GA client id and adds this to the user's tracking_context
        2) extracts the LMS user_id
        3) updates the user if necessary.

    Side effect:
        If the LMS user_id cannot be found, writes custom metric: 'ecommerce_missing_lms_user_id_middleware'

    """

    def process_request(self, request):
        user = request.user
        if user.is_authenticated():
            save_user = False
            tracking_context = user.tracking_context or {}

            # Check for the GA client id
            old_client_id = tracking_context.get('ga_client_id')
            ga_client_id = get_google_analytics_client_id(request)
            if ga_client_id and ga_client_id != old_client_id:
                tracking_context['ga_client_id'] = ga_client_id
                user.tracking_context = tracking_context
                save_user = True

            # The LMS user_id may already be present for the user. It may have been added from the jwt (see the
            # EDX_DRF_EXTENSIONS.JWT_PAYLOAD_USER_ATTRIBUTE_MAPPING settings) or by a previous call to this middleware.
            # If the id is not present, try to add it.
            if not user.lms_user_id:
                # Check for the lms_user_id in social auth
                lms_user_id_social_auth = self._get_lms_user_id_from_social_auth(user)
                if lms_user_id_social_auth:
                    user.lms_user_id = lms_user_id_social_auth
                    save_user = True
                    logger.info(u'Saving lms_user_id from social auth for user %s. Request path: %s, referrer: %s',
                                user.id, request.get_full_path(), request.META.get('HTTP_REFERER'))
                else:
                    # TODO: Change this to an error once we can successfully get the id from social auth and the db.
                    # See REVMI-249 and REVMI-269
                    monitoring_utils.set_custom_metric('ecommerce_missing_lms_user_id_middleware', user.id)
                    logger.warn(u'Could not find lms_user_id for user %s. Request path: %s, referrer: %s', user.id,
                                request.get_full_path(), request.META.get('HTTP_REFERER'))

            if save_user:
                user.save()

    def _get_lms_user_id_from_social_auth(self, user):
        """
        Return LMS user_id passed through social auth, if found.
        Returns None if not found.
        """
        try:
            auth_entries = user.social_auth.all()
            if auth_entries:
                for auth_entry in auth_entries:
                    lms_user_id_social_auth = auth_entry.extra_data.get(u'user_id')
                    if lms_user_id_social_auth:
                        return lms_user_id_social_auth
        except Exception:  # pylint: disable=broad-except
            logger.warn(u'Exception retrieving lms_user_id from social_auth for user %s.', user.id, exc_info=True)
