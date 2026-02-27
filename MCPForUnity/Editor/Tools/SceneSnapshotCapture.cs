using System;
using System.Collections.Generic;
using MCPForUnity.Editor.Helpers;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace MCPForUnity.Editor.Tools
{
    /// <summary>
    /// Captures a lightweight scene hierarchy snapshot for server-side ref graph ingestion.
    /// </summary>
    [McpForUnityTool("scene_snapshot_capture", AutoRegister = false)]
    public static class SceneSnapshotCapture
    {
        private const int DefaultMaxNodes = 2000;
        private const int MaxAllowedNodes = 10000;

        public static object HandleCommand(JObject @params)
        {
            @params ??= new JObject();

            bool includeInactive = ParamCoercion.CoerceBool(
                @params["includeInactive"] ?? @params["include_inactive"],
                false
            );
            bool includeComponents = ParamCoercion.CoerceBool(
                @params["includeComponents"] ?? @params["include_components"],
                false
            );
            int maxNodes = Mathf.Clamp(
                ParamCoercion.CoerceInt(@params["maxNodes"] ?? @params["max_nodes"], DefaultMaxNodes),
                1,
                MaxAllowedNodes
            );

            int? rootInstanceId = null;
            var rootToken = @params["rootInstanceId"] ?? @params["root_instance_id"];
            if (rootToken != null && rootToken.Type != JTokenType.Null)
            {
                int parsed = ParamCoercion.CoerceInt(rootToken, int.MinValue);
                if (parsed == int.MinValue)
                {
                    return new ErrorResponse("'rootInstanceId' must be a valid integer.");
                }

                rootInstanceId = parsed;
            }

            try
            {
                Scene snapshotScene = ResolveSnapshotScene();
                if (!snapshotScene.IsValid() || !snapshotScene.isLoaded)
                {
                    return new ErrorResponse("No valid loaded scene available for snapshot capture.");
                }

                var objects = new List<object>(Math.Min(maxNodes, 512));

                if (rootInstanceId.HasValue)
                {
                    var rootObject = EditorUtility.InstanceIDToObject(rootInstanceId.Value) as GameObject;
                    if (rootObject == null)
                    {
                        return new ErrorResponse($"Root GameObject with instance ID {rootInstanceId.Value} was not found.");
                    }

                    TraverseHierarchy(
                        rootObject.transform,
                        includeInactive,
                        includeComponents,
                        maxNodes,
                        objects
                    );
                }
                else
                {
                    var roots = snapshotScene.GetRootGameObjects();
                    foreach (var root in roots)
                    {
                        if (root == null)
                        {
                            continue;
                        }

                        TraverseHierarchy(
                            root.transform,
                            includeInactive,
                            includeComponents,
                            maxNodes,
                            objects
                        );

                        if (objects.Count >= maxNodes)
                        {
                            break;
                        }
                    }
                }

                bool truncated = objects.Count >= maxNodes;

                return new SuccessResponse(
                    $"Captured scene snapshot with {objects.Count} objects.",
                    new
                    {
                        sceneName = snapshotScene.name,
                        objects,
                        truncated,
                    }
                );
            }
            catch (Exception e)
            {
                McpLog.Error($"[SceneSnapshotCapture] Failed to capture snapshot: {e}");
                return new ErrorResponse($"Failed to capture scene snapshot: {e.Message}");
            }
        }

        private static Scene ResolveSnapshotScene()
        {
            var prefabStage = PrefabStageUtility.GetCurrentPrefabStage();
            if (prefabStage != null)
            {
                return prefabStage.scene;
            }

            return SceneManager.GetActiveScene();
        }

        private static void TraverseHierarchy(
            Transform node,
            bool includeInactive,
            bool includeComponents,
            int maxNodes,
            List<object> output
        )
        {
            if (node == null || output.Count >= maxNodes)
            {
                return;
            }

            var gameObject = node.gameObject;
            if (gameObject != null && (includeInactive || gameObject.activeInHierarchy))
            {
                output.Add(SerializeObject(gameObject, includeComponents));
            }

            if (output.Count >= maxNodes)
            {
                return;
            }

            foreach (Transform child in node)
            {
                TraverseHierarchy(child, includeInactive, includeComponents, maxNodes, output);
                if (output.Count >= maxNodes)
                {
                    return;
                }
            }
        }

        private static object SerializeObject(GameObject gameObject, bool includeComponents)
        {
            int? parentInstanceId = null;
            if (gameObject.transform.parent != null)
            {
                parentInstanceId = gameObject.transform.parent.gameObject.GetInstanceID();
            }

            string layerName = LayerMask.LayerToName(gameObject.layer);
            if (string.IsNullOrEmpty(layerName))
            {
                layerName = gameObject.layer.ToString();
            }

            var components = new List<string>();
            if (includeComponents)
            {
                foreach (var component in gameObject.GetComponents<Component>())
                {
                    if (component == null)
                    {
                        continue;
                    }

                    components.Add(component.GetType().Name);
                }
            }

            return new
            {
                instanceId = gameObject.GetInstanceID(),
                name = gameObject.name,
                path = GameObjectLookup.GetGameObjectPath(gameObject),
                parentInstanceId,
                active = gameObject.activeSelf,
                layer = layerName,
                tag = gameObject.tag,
                components,
            };
        }
    }
}
