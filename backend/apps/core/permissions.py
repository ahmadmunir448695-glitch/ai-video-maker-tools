from rest_framework import permissions


class IsOwner(permissions.BasePermission):
    """Require an authenticated user, and for object routes require ownership.

    ``has_permission`` is implemented deliberately: ``BasePermission`` returns
    ``True`` from it by default, so a view that sets ``permission_classes =
    [IsOwner]`` would otherwise replace the project-wide ``IsAuthenticated``
    default and let anonymous requests into list and create actions.

    Views are still expected to filter their querysets by owner — this is the
    second lock, so a lookup that slips past a filter cannot leak a row.
    """

    message = "You do not have permission to act on this resource."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        owner = getattr(obj, "owner", None)
        return bool(owner is not None and owner == request.user)
