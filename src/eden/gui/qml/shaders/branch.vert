// A branch segment of the garden's tree (garden.py, branch_table): it grows between its two
// moments INSTANCE_DATA.xy: a green shoot at first, it thickens and turns to bark as it matures.
VARYING vec3 vColor;

vec3 breeze(vec3 p)
{
    // a light wind: the higher the point, the more it moves
    float h = clamp(p.y / 4.5, 0.0, 1.0);
    float k = h * h * 0.045;
    return vec3(sin(time * 0.9 + p.y * 0.7) * k, 0.0, sin(time * 0.7 + p.x * 0.5 + 1.3) * k * 0.7);
}

void MAIN()
{
    float t0 = INSTANCE_DATA.x;
    float f = clamp((growth - t0) / max(INSTANCE_DATA.y - t0, 0.0001), 0.0, 1.0);
    float girth = step(0.0001, f) * mix(0.06, 1.0, smoothstep(t0, 1.0, growth));
    VERTEX.xz *= girth * mix(1.0, INSTANCE_DATA.z, VERTEX.y);
    VERTEX.y *= f;
    vec4 world = INSTANCE_MODEL_MATRIX * vec4(VERTEX, 1.0);
    world.xyz += breeze(world.xyz);
    vColor = mix(vec3(0.36, 0.56, 0.16), COLOR.rgb, smoothstep(t0 + 0.04, t0 + 0.3, growth));
    POSITION = VIEWPROJECTION_MATRIX * world;
}
