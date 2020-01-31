# Copyright (c) 2017 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import pprint
import re
import maya.cmds as cmds
import maya.mel as mel
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()


class MayaSessionGeometryZombiePublishPlugin(HookBaseClass):
    """
    Plugin for publishing an open maya session.

    This hook relies on functionality found in the base file publisher hook in
    the publish2 app and should inherit from it in the configuration. The hook
    setting for this plugin should look something like this::

        hook: "{self}/publish_file.py:{engine}/tk-multi-publish2/basic/publish_session.py"

    """

    # NOTE: The plugin icon and name are defined by the base file plugin.

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does (:class:`str`).
        The string can contain html for formatting for display in the UI (any
        html tags supported by Qt's rich text engine).
        """
        return """
        <p>
        This plugin handles exporting and publishing Maya shader networks.
        Collected mesh shaders are exported to disk as .ma files that can
        be loaded by artists downstream. This is a simple, example
        implementation and not meant to be a robust, battle-tested solution for
        shader or texture management on production.
        </p>
        """

    @property
    def settings(self):
        """
        A :class:`dict` defining the configuration interface for this plugin.
        The dictionary can include any number of settings required by the
        plugin, and takes the form::
            {
                <setting_name>: {
                    "type": <type>,
                    "default": <default>,
                    "description": <description>
                },
                <setting_name>: {
                    "type": <type>,
                    "default": <default>,
                    "description": <description>
                },
                ...
            }
        The keys in the dictionary represent the names of the settings. The
        values are a dictionary comprised of 3 additional key/value pairs.
        * ``type``: The type of the setting. This should correspond to one of
          the data types that toolkit accepts for app and engine settings such
          as ``hook``, ``template``, ``string``, etc.
        * ``default``: The default value for the settings. This can be ``None``.
        * ``description``: A description of the setting as a string.
        The values configured for the plugin will be supplied via settings
        parameter in the :meth:`accept`, :meth:`validate`, :meth:`publish`, and
        :meth:`finalize` methods.
        The values also drive the custom UI defined by the plugin whick allows
        artists to manipulate the settings at runtime. See the
        :meth:`create_settings_widget`, :meth:`set_ui_settings`, and
        :meth:`get_ui_settings` for additional information.
        .. note:: See the hooks defined in the publisher app's ``hooks/`` folder
           for additional example implementations.
        """
        # inherit the settings from the base publish plugin
        plugin_settings = super(MayaSessionGeometryZombiePublishPlugin, self).settings or {}

        # settings specific to this class
        meshGroup_publish_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published shader networks. "
                               "Should correspond to a template defined in "
                               "templates.yml.",
            }
        }

        # update the base settings
        plugin_settings.update(meshGroup_publish_settings)

        return plugin_settings

    @property
    def item_filters(self):
        """
        A :class:`list` of item type wildcard :class:`str` objects that this
        plugin is interested in.
        As items are collected by the collector hook, they are given an item
        type string (see :meth:`~.processing.Item.create_item`). The strings
        provided by this property will be compared to each collected item's
        type.
        Only items with types matching entries in this list will be considered
        by the :meth:`accept` method. As such, this method makes it possible to
        quickly identify which items the plugin may be interested in. Any
        sophisticated acceptance logic is deferred to the :meth:`accept` method.
        Strings can contain glob patters such as ``*``, for example ``["maya.*",
        "file.maya"]``.
        """
        # NOTE: this matches the item type defined in the collector.
        return ["maya.session.mesh"]

    def accept(self, settings, item):
        """
        This method is called by the publisher to see if the plugin accepts the
        supplied item for processing.
        Only items matching the filters defined via the :data:`item_filters`
        property will be presented to this method.
        A publish task will be generated for each item accepted here.
        This method returns a :class:`dict` of the following form::
            {
                "accepted": <bool>,
                "enabled": <bool>,
                "visible": <bool>,
                "checked": <bool>,
            }
        The keys correspond to the acceptance state of the supplied item. Not
        all keys are required. The keys are defined as follows:
        * ``accepted``: Indicates if the plugin is interested in this value at all.
          If ``False``, no task will be created for this plugin. Required.
        * ``enabled``: If ``True``, the created task will be enabled in the UI,
          otherwise it will be disabled (no interaction allowed). Optional,
          ``True`` by default.
        * ``visible``: If ``True``, the created task will be visible in the UI,
          otherwise it will be hidden. Optional, ``True`` by default.
        * ``checked``: If ``True``, the created task will be checked in the UI,
          otherwise it will be unchecked. Optional, ``True`` by default.
        In addition to the item, the configured settings for this plugin are
        supplied. The information provided by each of these arguments can be
        used to decide whether to accept the item.
        For example, the item's ``properties`` :class:`dict` may house meta data
        about the item, populated during collection. This data can be used to
        inform the acceptance logic.
        :param dict settings: The keys are strings, matching the keys returned
            in the :data:`settings` property. The values are
            :class:`~.processing.Setting` instances.
        :param item: The :class:`~.processing.Item` instance to process for
            acceptance.
        :returns: dictionary with boolean keys accepted, required and enabled
        """

        # by default we will accept the item. if any of the checks below fail,
        # we'll set this to False.
        accepted = True

        # a handle on the instance of the publisher app
        publisher = self.parent

        # extract the value of the template configured for this instance
        template_name = settings["Publish Template"].value

        # ensure a work file template is available on the parent maya session
        # item.
        work_template = item.parent.properties.get("work_template")
        if not work_template:
            self.logger.debug(
                "A work template is required for the session item in order to "
                "publish session geometry. Not accepting session geom item."
            )
            accepted = False

        # ensure the publish template is defined and valid
        publish_template = publisher.get_template_by_name(template_name)
        self.logger.debug("TEMPLATE NAME: " + str(template_name))
        if not publish_template:
            self.logger.debug(
                "A valid publish template could not be determined for the "
                "session geometry item. Not accepting the item."
            )
            accepted = False

        # we've validated the publish template. add it to the item properties
        # for use in subsequent methods
        item.properties["publish_template"] = publish_template

        # because a publish template is configured, disable context change. This
        # is a temporary measure until the publisher handles context switching
        # natively.
        item.context_change_allowed = False

        return {
            "accepted": accepted,
            "checked": True
        }
    
    def validate(self, settings, item):
        """
        Validates the given item, ensuring it is ok to publish.
        Returns a boolean to indicate whether the item is ready to publish.
        Returning ``True`` will indicate that the item is ready to publish. If
        ``False`` is returned, the publisher will disallow publishing of the
        item.
        An exception can also be raised to indicate validation failed.
        When an exception is raised, the error message will be displayed as a
        tooltip on the task as well as in the logging view of the publisher.
        :param dict settings: The keys are strings, matching the keys returned
            in the :data:`settings` property. The values are
            :class:`~.processing.Setting` instances.
        :param item: The :class:`~.processing.Item` instance to validate.
        :returns: True if item is valid, False otherwise.
        """

        path = _session_path()

        # ---- ensure the session has been saved

        if not path:
            # the session still requires saving. provide a save button.
            # validation fails.
            error_msg = "The Maya session has not been saved."
            self.logger.error(
                error_msg,
                extra=_get_save_as_action()
            )
            raise Exception(error_msg)

        # get the normalized path. checks that separators are matching the
        # current operating system, removal of trailing separators and removal
        # of double separators, etc.
        path = sgtk.util.ShotgunPath.normalize(path)

        object_name = item.properties["groupName"]

        # check that there is still geometry in the scene:
        if (not cmds.ls(assemblies=True) or
            not cmds.ls(object_name, dag=True, type="mesh")):
            error_msg = (
                "Validation failed because there are no meshes in the scene "
                "to export shaders for. You can uncheck this plugin or create "
                "meshes with shaders to export to avoid this error."
            )
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # get the configured work file template
        work_template = item.parent.properties.get("work_template")
        publish_template = item.properties.get("publish_template")

        # get the current scene path and extract fields from it using the work
        # template:
        work_fields = work_template.get_fields(path)

        # we want to override the {name} token of the publish path with the
        # name of the object being exported. get the name stored by the
        # collector and remove any non-alphanumeric characters
        object_display = re.sub(r'[\W_]+', '', object_name)
        work_fields["name"] = object_display

        # set the display name as the name to use in SG to represent the publish
        item.properties["publish_name"] = object_display

        # ensure the fields work for the publish template
        missing_keys = publish_template.missing_keys(work_fields)
        if missing_keys:
            error_msg = "Work file '%s' missing keys required for the " \
                        "publish template: %s" % (path, missing_keys)
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # create the publish path by applying the fields. store it in the item's
        # properties. Also set the publish_path to be explicit.
        item.properties["path"] = publish_template.apply_fields(work_fields)
        item.properties["publish_path"] = item.properties["path"]

        # use the work file's version number when publishing
        if "version" in work_fields:
            item.properties["publish_version"] = work_fields["version"]

        # run the base class validation
        return super(MayaSessionGeometryZombiePublishPlugin, self).validate(
            settings, item)

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        publisher = self.parent

        # get the path to create and publish
        publish_path = item.properties["path"]


        # ensure the publish folder exists:
        publish_folder = os.path.dirname(publish_path)
        self.parent.ensure_folder_exists(publish_folder)

        # set the alembic args that make the most sense when working with Mari.
        # These flags will ensure the export of an Alembic file that contains
        # all visible geometry from the current scene together with UV's and
        # face sets for use in Mari.
        alembic_args = [
            # only renderable objects (visible and not templated)
            "-renderableOnly",
            # write shading group set assignments (Maya 2015+)
            "-writeFaceSets",
            # write uv's (only the current uv set gets written)
            "-uvWrite",
            # strip namespaces
            "-stripNamespaces",
            # set worldSpace
            "-worldSpace",
            #
            "-writeVisibility",
    
        ]

        # find the animated frame range to use:
        start_frame, end_frame = _find_scene_animation_range()
        if start_frame and end_frame:
            alembic_args.append("-fr %d %d" % (start_frame, end_frame))

        # set root
        mesh_group = item.properties["groupName"]
        alembic_args.append("-root %s" % mesh_group)

        # Set the output path: 
        # Note: The AbcExport command expects forward slashes!
        alembic_args.append("-file '%s'" % publish_path.replace("\\", "/"))

        # build the export command.  Note, use AbcExport -help in Maya for
        # more detailed Alembic export help
        abc_export_cmd = ("AbcExport -j \"%s\"" % " ".join(alembic_args))
        
        
        # ...and execute it:
        try:
            self.parent.log_debug("Executing command: %s" % abc_export_cmd)
            mel.eval(abc_export_cmd)
        except Exception, e:
            self.logger.error("Failed to export Geometry: %s" % e)
            return

        # Now that the path has been generated, hand it off to the
        super(MayaSessionGeometryZombiePublishPlugin, self).publish(settings, item)


def _find_scene_animation_range():
    """
    Find the animation range from the current scene.
    """
    # look for any animation in the scene:
    animation_curves = cmds.ls(typ="animCurve")

    # if there aren't any animation curves then just return
    # a single frame:
    if not animation_curves:
        return 1, 1

    # something in the scene is animated so return the
    # current timeline.  This could be extended if needed
    # to calculate the frame range of the animated curves.
    start = int(cmds.playbackOptions(q=True, min=True))
    end = int(cmds.playbackOptions(q=True, max=True))

    return start, end


def _session_path():
    """
    Return the path to the current session
    :return:
    """
    path = cmds.file(query=True, sn=True)

    if isinstance(path, unicode):
        path = path.encode("utf-8")

    return path


def _get_save_as_action():
    """
    Simple helper for returning a log action dict for saving the session
    """

    engine = sgtk.platform.current_engine()

    # default save callback
    callback = cmds.SaveScene

    # if workfiles2 is configured, use that for file save
    if "tk-multi-workfiles2" in engine.apps:
        app = engine.apps["tk-multi-workfiles2"]
        if hasattr(app, "show_file_save_dlg"):
            callback = app.show_file_save_dlg

    return {
        "action_button": {
            "label": "Save As...",
            "tooltip": "Save the current session",
            "callback": callback
        }
    }
