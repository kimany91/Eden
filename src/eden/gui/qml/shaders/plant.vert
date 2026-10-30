// Grass and flowers of the lawn: they sway, the tips more than the foot.
VARYING vec3 vColor;

void MAIN()
{
    vec3 foot = INSTANCE_MODEL_MATRIX[3].xyz;
    vec4 world = INSTANCE_MODEL_MATRIX * vec4(VERTEX, 1.0);
    float h = max(world.y - foot.y, 0.0);
    float phase = dot(foot, vec3(1.3, 0.0, 0.9));
    world.x += sin(time * 1.3 + phase) * h * 0.22;
    world.z += sin(time * 1.1 + phase * 1.7) * h * 0.12;
    vColor = COLOR.rgb * INSTANCE_COLOR.rgb;
    POSITION = VIEWPROJECTION_MATRIX * world;
}
