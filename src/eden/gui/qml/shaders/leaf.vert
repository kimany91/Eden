// A leaf of the garden's tree (garden.py, leaf_table): it opens between INSTANCE_DATA.x and .y
// with a small overshoot, like a bud bursting; the sprout's first two leaves wither between
// .z and .w. It flutters round its stalk and follows the branches in the wind.
VARYING vec3 vColor;

vec3 breeze(vec3 p)
{
    float h = clamp(p.y / 4.5, 0.0, 1.0);
    float k = h * h * 0.045;
    return vec3(sin(time * 0.9 + p.y * 0.7) * k, 0.0, sin(time * 0.7 + p.x * 0.5 + 1.3) * k * 0.7);
}

void MAIN()
{
    float f = clamp((growth - INSTANCE_DATA.x) / max(INSTANCE_DATA.y - INSTANCE_DATA.x, 0.0001), 0.0, 1.0);
    float g = f - 1.0;
    float open = f <= 0.0 ? 0.0 : 1.0 + 2.7 * g * g * g + 1.7 * g * g;
    float alive = 1.0 - smoothstep(INSTANCE_DATA.z, INSTANCE_DATA.w, growth);
    vec3 stalk = INSTANCE_MODEL_MATRIX[3].xyz;
    VERTEX.z += sin(time * 2.4 + dot(stalk, vec3(3.1, 1.7, 2.3))) * 0.1 * VERTEX.y;
    VERTEX *= max(open, 0.0) * alive;
    vec4 world = INSTANCE_MODEL_MATRIX * vec4(VERTEX, 1.0);
    world.xyz += breeze(world.xyz);
    vColor = COLOR.rgb * INSTANCE_COLOR.rgb;
    POSITION = VIEWPROJECTION_MATRIX * world;
}
