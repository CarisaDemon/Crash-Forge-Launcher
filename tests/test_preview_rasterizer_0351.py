"""v0.3.51 texture-accurate and responsive native previews."""
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import forge_model_preview as model
from forge_preview_rasterizer import render_scene, MAX_HEIGHT

class PreviewRasterizerTests(unittest.TestCase):
    def make_scene(self,material="Atlas"):
        scene=model.Scene(
            vertices=[(0.0,0.0,0.0),(1.0,0.0,0.0),(0.0,1.0,0.0)],
            faces=[(0,1,2,0,1,2,material)],
            uvs=[(0.0,0.0),(1.0,0.0),(0.0,1.0)],
            textures={material:Path("sample.png")},colors=[],
            kind="OBJ",source="test",description="UV triangle")
        return scene
    @staticmethod
    def atlas():
        arr=np.zeros((32,32,3),dtype=np.uint8)
        for y in range(32):
            for x in range(32):
                arr[y,x]=(int(255*x/31),int(255*y/31),30)
        return Image.fromarray(arr,mode="RGB")
    def test_uv_per_pixel_not_a_single_face_color(self):
        texture=self.atlas()
        scene=self.make_scene()
        img=render_scene(scene,300,220,yaw=0,pitch=0,zoom=1.0,
                         center=(.5,.5,0.0),normalizer=1,
                         texture_loader=lambda _:texture)
        pixels=np.asarray(img)
        color_samples=pixels[(pixels[:,:,0]>28)&(pixels[:,:,2]<60)]
        # One-color-per-triangle bug produces only a tiny unique-color set.
        colors=np.unique(color_samples,axis=0)
        self.assertGreater(len(colors),55,
              "The atlas should vary across pixels inside the same triangle.")
    def test_depth_buffer_keeps_nearer_triangle_on_top(self):
        scene=self.make_scene()
        scene.vertices += [(0.0,0.0,0.8),(1.0,0.0,.8),(0.0,1.0,.8)]
        scene.uvs += [(0,0),(1,0),(0,1)]
        scene.faces=[(3,4,5,3,4,5,"Front"),
                     (0,1,2,0,1,2,"Back")] # Render far one LAST.
        scene.textures={"Front":Path("front.png"),
                        "Back":Path("back.png")}
        def texture_loader(path):
            return Image.new("RGB",(8,8),
                (245,24,22) if path.name=="front.png" else (24,24,245))
        pic=render_scene(scene,320,220,yaw=0,pitch=0,zoom=1,
            center=(.5,.5,0),normalizer=1,texture_loader=texture_loader)
        rgb=np.asarray(pic)
        self.assertGreater(int(np.count_nonzero(
            (rgb[:,:,0]>200)&(rgb[:,:,2]<80))),70)
        # Where the front and back triangles overlap, blue cannot overwrite
        # foreground red even though the blue back face is later in the list.
        self.assertEqual(int(np.count_nonzero(
            (rgb[:,:,2]>200)&(rgb[:,:,0]<80))),0)
    def test_presentation_is_capped_without_changing_source_model(self):
        scene=self.make_scene()
        before=(tuple(scene.vertices),tuple(scene.uvs),tuple(scene.faces))
        img=render_scene(scene,1800,900,center=(.5,.5,0),normalizer=1,
                          texture_loader=lambda _:self.atlas())
        self.assertLessEqual(img.width,1200)
        self.assertEqual(img.height,MAX_HEIGHT)
        self.assertEqual((tuple(scene.vertices),
                          tuple(scene.uvs),tuple(scene.faces)),before)
    def test_missing_texture_still_does_not_crash(self):
        scene=self.make_scene()
        result=render_scene(scene,255,190,
                     center=(.5,.5,0),normalizer=1,
                     texture_loader=lambda _:None)
        self.assertEqual(result.size,(255,190))
    def test_small_viewport_and_visible_thumb_height(self):
        preview=Path(model.__file__).read_text(encoding="utf-8")
        gui=Path(__file__).resolve().parents[1]/"companion_tools"/"mod_packager"/"mod_packager_gui.py"
        content=gui.read_text(encoding="utf-8")
        self.assertIn("outer.pack_propagate(False)",preview)
        self.assertIn("self.height=height",preview)
        self.assertIn("self.canvas=tk.Canvas(outer,height=121",preview)
        self.assertIn('self.main_split=tk.PanedWindow(',content)
        self.assertIn('self.right_split=tk.PanedWindow(',content)
        self.assertIn('self.layout.register_pane("preview_textures", self.right_split)',content)

if __name__=="__main__":
    unittest.main()
