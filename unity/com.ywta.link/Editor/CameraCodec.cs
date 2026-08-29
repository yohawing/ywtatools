using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;

namespace YWTA.Link.Unity
{
    internal sealed class CameraBody
    {
        public CameraEntityRef entity_ref;
        public CameraTransform transform;
        public TimeValue time;
        public string projection;
        public double? focal_length;
        public double? horizontal_aperture;
        public double? vertical_aperture;
        public double[] aperture_offset;
        public double[] clipping_range;
        public double? focus_distance;
        public double? f_stop;
        public double? exposure;
        public double? orthographic_size;
        public string film_fit;
        public string gate_fit;
        public double aspect_ratio;
        public string change_id;
    }

    internal sealed class CameraEntityRef
    {
        public string entity_id;
        public string kind;
        public string display_name;
        public string @namespace;
    }

    internal sealed class CameraTransform
    {
        public CameraEntityRef entity_ref;
        public double[] translation;
        public double[] rotation;
        public double[] scale;
        public CameraCoordinateSystem coordinate_system;
        public string unit;
        public object rotation_order;
    }

    internal sealed class CameraCoordinateSystem
    {
        public string space;
        public string handedness;
        public string up_axis;
        public string forward_axis;
        public string parent_entity_id;
    }

    internal static class CameraCodec
    {
        internal static CameraBody Decode(LinkFrame frame)
        {
            if (frame.Body.Length != 0) throw new FormatException("Camera JSON must not contain raw bytes");
            return Decode(StrictJson.Object(frame.Root, "body"));
        }

        internal static CameraBody Decode(Dictionary<string, object> body)
        {
            StrictJson.ExactFields(body, "entity_ref", "transform", "time", "projection", "focal_length",
                "horizontal_aperture", "vertical_aperture", "aperture_offset", "clipping_range",
                "focus_distance", "f_stop", "exposure", "orthographic_size", "film_fit", "gate_fit",
                "aspect_ratio", "change_id");
            CameraEntityRef entity = Entity(StrictJson.Object(body, "entity_ref"));
            CameraTransform transform = Transform(StrictJson.Object(body, "transform"));
            if (!SameEntity(entity, transform.entity_ref)) throw new FormatException("Camera entity references must match");
            string projection = StrictJson.String(body, "projection");
            if (projection != "perspective" && projection != "orthographic") throw new FormatException("Unsupported projection");
            CameraBody result = new CameraBody
            {
                entity_ref = entity,
                transform = transform,
                time = Time(StrictJson.Object(body, "time")),
                projection = projection,
                focal_length = OptionalPositive(body, "focal_length"),
                horizontal_aperture = OptionalPositive(body, "horizontal_aperture"),
                vertical_aperture = OptionalPositive(body, "vertical_aperture"),
                aperture_offset = OptionalVector(body, "aperture_offset"),
                clipping_range = Vector(body, "clipping_range", true),
                focus_distance = OptionalPositive(body, "focus_distance"),
                f_stop = OptionalPositive(body, "f_stop"),
                exposure = OptionalNumber(body, "exposure"),
                orthographic_size = OptionalPositive(body, "orthographic_size"),
                film_fit = OptionalFit(body, "film_fit"),
                gate_fit = OptionalFit(body, "gate_fit"),
                aspect_ratio = Positive(body, "aspect_ratio"),
                change_id = StrictJson.String(body, "change_id")
            };
            if (result.clipping_range[0] >= result.clipping_range[1]) throw new FormatException("Clipping range must increase");
            if (projection == "perspective")
            {
                if (!result.focal_length.HasValue || !result.horizontal_aperture.HasValue ||
                    !result.vertical_aperture.HasValue || result.aperture_offset == null || result.orthographic_size.HasValue)
                    throw new FormatException("Perspective lens fields are invalid");
            }
            else if (result.focal_length.HasValue || result.horizontal_aperture.HasValue ||
                     result.vertical_aperture.HasValue || result.aperture_offset != null || !result.orthographic_size.HasValue)
                throw new FormatException("Orthographic lens fields are invalid");
            return result;
        }

        internal static string Encode(CameraBody value)
        {
            // Encode前にも同じstrict contractを通し、内部生成値の逸脱をwireへ出さない。
            string json = RawEncode(value);
            return RawEncode(Decode(StrictJson.ParseObject(json)));
        }

        private static string RawEncode(CameraBody c)
        {
            StringBuilder b = new StringBuilder(1024).Append('{');
            b.Append("\"entity_ref\":"); EntityJson(b, c.entity_ref);
            b.Append(",\"transform\":"); TransformJson(b, c.transform);
            b.Append(",\"time\":"); TimeJson(b, c.time);
            b.Append(",\"projection\":"); StringJson(b, c.projection);
            NullableNumber(b, "focal_length", c.focal_length); NullableNumber(b, "horizontal_aperture", c.horizontal_aperture);
            NullableNumber(b, "vertical_aperture", c.vertical_aperture); NullableVector(b, "aperture_offset", c.aperture_offset);
            VectorJson(b, "clipping_range", c.clipping_range); NullableNumber(b, "focus_distance", c.focus_distance);
            NullableNumber(b, "f_stop", c.f_stop); NullableNumber(b, "exposure", c.exposure);
            NullableNumber(b, "orthographic_size", c.orthographic_size); NullableString(b, "film_fit", c.film_fit);
            NullableString(b, "gate_fit", c.gate_fit); NumberJson(b, "aspect_ratio", c.aspect_ratio);
            b.Append(",\"change_id\":"); StringJson(b, c.change_id); return b.Append('}').ToString();
        }

        private static CameraEntityRef Entity(Dictionary<string, object> value)
        {
            StrictJson.ExactFields(value, "entity_id", "kind", "display_name", "namespace");
            return new CameraEntityRef { entity_id = StrictJson.String(value, "entity_id"), kind = StrictJson.String(value, "kind"),
                display_name = StrictJson.String(value, "display_name"), @namespace = OptionalString(value, "namespace") };
        }

        private static CameraTransform Transform(Dictionary<string, object> value)
        {
            StrictJson.ExactFields(value, "entity_ref", "translation", "rotation", "scale", "coordinate_system", "unit", "rotation_order");
            CameraCoordinateSystem coordinates = Coordinates(StrictJson.Object(value, "coordinate_system"));
            string unit = StrictJson.String(value, "unit");
            if (unit != "millimeter" && unit != "centimeter" && unit != "meter") throw new FormatException("Unsupported transform unit");
            StrictJson.Null(value, "rotation_order");
            double[] rotation = Array(value, "rotation", 4);
            double norm = Math.Sqrt(rotation[0] * rotation[0] + rotation[1] * rotation[1] + rotation[2] * rotation[2] + rotation[3] * rotation[3]);
            if (Math.Abs(norm - 1.0) > 1e-6) throw new FormatException("Rotation quaternion must be normalized");
            for (int i = 0; i < rotation.Length; ++i) rotation[i] /= norm;
            if (rotation[3] < 0 || (rotation[3] == 0 && (rotation[0] < 0 ||
                (rotation[0] == 0 && (rotation[1] < 0 || (rotation[1] == 0 && rotation[2] < 0))))))
                for (int i = 0; i < rotation.Length; ++i) rotation[i] = -rotation[i];
            return new CameraTransform { entity_ref = Entity(StrictJson.Object(value, "entity_ref")), translation = Array(value, "translation", 3),
                rotation = rotation, scale = Array(value, "scale", 3), coordinate_system = coordinates, unit = unit, rotation_order = null };
        }

        private static CameraCoordinateSystem Coordinates(Dictionary<string, object> value)
        {
            StrictJson.ExactFields(value, "space", "handedness", "up_axis", "forward_axis", "parent_entity_id");
            CameraCoordinateSystem result = new CameraCoordinateSystem { space = StrictJson.String(value, "space"), handedness = StrictJson.String(value, "handedness"),
                up_axis = StrictJson.String(value, "up_axis"), forward_axis = StrictJson.String(value, "forward_axis"), parent_entity_id = OptionalString(value, "parent_entity_id") };
            if (result.space != "world" && result.space != "parent") throw new FormatException("Unsupported coordinate space");
            if (result.handedness != "right" && result.handedness != "left") throw new FormatException("Unsupported handedness");
            if (!Axis(result.up_axis) || !Axis(result.forward_axis) || result.up_axis[1] == result.forward_axis[1])
                throw new FormatException("Coordinate axes are invalid");
            if ((result.space == "world") != (result.parent_entity_id == null))
                throw new FormatException("Coordinate parent does not match space");
            return result;
        }

        private static TimeValue Time(Dictionary<string, object> value)
        {
            StrictJson.ExactFields(value, "time", "start", "end_exclusive", "timebase", "sample_rate");
            long tick = StrictJson.Integer(value, "time"); StrictJson.Null(value, "start"); StrictJson.Null(value, "end_exclusive"); StrictJson.Null(value, "sample_rate");
            Dictionary<string, object> rate = StrictJson.Object(value, "timebase"); StrictJson.ExactFields(rate, "rate_num", "rate_den");
            long numerator = StrictJson.PositiveInteger(rate, "rate_num"); long denominator = StrictJson.PositiveInteger(rate, "rate_den");
            if (numerator > int.MaxValue || denominator > int.MaxValue || Gcd(numerator, denominator) != 1) throw new FormatException("Timebase must be a reduced 32-bit rate");
            return new TimeValue { time = tick, timebase = new RationalRate { rate_num = numerator, rate_den = denominator } };
        }

        private static double[] Array(Dictionary<string, object> body, string field, int length)
        {
            List<object> values = StrictJson.Array(body, field); if (values.Count != length) throw new FormatException(field + " has wrong length");
            double[] result = new double[length]; for (int i = 0; i < length; ++i) result[i] = Number(values[i], field); return result;
        }
        private static double[] Vector(Dictionary<string, object> body, string field, bool positive) { double[] v = Array(body, field, 2); if (positive && (v[0] <= 0 || v[1] <= 0)) throw new FormatException(field + " must be positive"); return v; }
        private static double[] OptionalVector(Dictionary<string, object> body, string field) { return body[field] == null ? null : Vector(body, field, false); }
        private static double? OptionalNumber(Dictionary<string, object> body, string field) { return body[field] == null ? (double?)null : StrictJson.Number(body, field); }
        private static double? OptionalPositive(Dictionary<string, object> body, string field) { double? v = OptionalNumber(body, field); if (v <= 0) throw new FormatException(field + " must be positive"); return v; }
        private static double Positive(Dictionary<string, object> body, string field) { double v = StrictJson.Number(body, field); if (v <= 0) throw new FormatException(field + " must be positive"); return v; }
        private static string OptionalFit(Dictionary<string, object> body, string field) { string v = OptionalString(body, field); if (v != null && v != "horizontal" && v != "vertical" && v != "fill" && v != "overscan") throw new FormatException("Unsupported " + field); return v; }
        private static string OptionalString(Dictionary<string, object> value, string field) { if (value[field] == null) return null; return StrictJson.String(value, field); }
        private static double Number(object value, string field) { var wrapper = new Dictionary<string, object> { { field, value } }; return StrictJson.Number(wrapper, field); }
        private static bool SameEntity(CameraEntityRef a, CameraEntityRef b) { return a.entity_id == b.entity_id && a.kind == b.kind && a.display_name == b.display_name && a.@namespace == b.@namespace; }
        private static bool Axis(string value) { return value == "+x" || value == "-x" || value == "+y" || value == "-y" || value == "+z" || value == "-z"; }
        private static long Gcd(long a, long b) { while (b != 0) { long remainder = a % b; a = b; b = remainder; } return a; }

        private static void EntityJson(StringBuilder b, CameraEntityRef e) { b.Append('{').Append("\"entity_id\":"); StringJson(b, e.entity_id); b.Append(",\"kind\":"); StringJson(b, e.kind); b.Append(",\"display_name\":"); StringJson(b, e.display_name); NullableString(b, "namespace", e.@namespace); b.Append('}'); }
        private static void TransformJson(StringBuilder b, CameraTransform t) { b.Append('{').Append("\"entity_ref\":"); EntityJson(b, t.entity_ref); VectorJson(b, "translation", t.translation); VectorJson(b, "rotation", t.rotation); VectorJson(b, "scale", t.scale); b.Append(",\"coordinate_system\":{\"space\":"); StringJson(b, t.coordinate_system.space); b.Append(",\"handedness\":"); StringJson(b, t.coordinate_system.handedness); b.Append(",\"up_axis\":"); StringJson(b, t.coordinate_system.up_axis); b.Append(",\"forward_axis\":"); StringJson(b, t.coordinate_system.forward_axis); NullableString(b, "parent_entity_id", t.coordinate_system.parent_entity_id); b.Append('}'); b.Append(",\"unit\":"); StringJson(b, t.unit); b.Append(",\"rotation_order\":null}"); }
        private static void TimeJson(StringBuilder b, TimeValue t) { b.Append("{\"time\":").Append(t.time.ToString(CultureInfo.InvariantCulture)).Append(",\"start\":null,\"end_exclusive\":null,\"timebase\":{\"rate_num\":").Append(t.timebase.rate_num).Append(",\"rate_den\":").Append(t.timebase.rate_den).Append("},\"sample_rate\":null}"); }
        private static void NullableNumber(StringBuilder b, string n, double? v) { b.Append(",\"").Append(n).Append("\":"); if (v.HasValue) b.Append(v.Value.ToString("R", CultureInfo.InvariantCulture)); else b.Append("null"); }
        private static void NumberJson(StringBuilder b, string n, double v) { NullableNumber(b, n, v); }
        private static void NullableVector(StringBuilder b, string n, double[] v) { b.Append(",\"").Append(n).Append("\":"); if (v == null) b.Append("null"); else VectorContents(b, v); }
        private static void VectorJson(StringBuilder b, string n, double[] v) { b.Append(",\"").Append(n).Append("\":"); VectorContents(b, v); }
        private static void VectorContents(StringBuilder b, double[] v) { b.Append('['); for (int i = 0; i < v.Length; ++i) { if (i != 0) b.Append(','); b.Append(v[i].ToString("R", CultureInfo.InvariantCulture)); } b.Append(']'); }
        private static void NullableString(StringBuilder b, string n, string v) { b.Append(",\"").Append(n).Append("\":"); if (v == null) b.Append("null"); else StringJson(b, v); }
        private static void StringJson(StringBuilder b, string v) { if (string.IsNullOrWhiteSpace(v)) throw new FormatException("String must not be empty"); b.Append('"'); foreach (char c in v) { switch (c) { case '"': b.Append("\\\""); break; case '\\': b.Append("\\\\"); break; case '\b': b.Append("\\b"); break; case '\f': b.Append("\\f"); break; case '\n': b.Append("\\n"); break; case '\r': b.Append("\\r"); break; case '\t': b.Append("\\t"); break; default: if (c < 0x20) b.Append("\\u").Append(((int)c).ToString("x4")); else b.Append(c); break; } } b.Append('"'); }
    }
}
