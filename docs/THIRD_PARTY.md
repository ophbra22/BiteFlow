# Third-party resources

- TensorFlow/Keras: Apache 2.0 project, [tensorflow.org](https://www.tensorflow.org/).
- MobileNetV2 checkpoint: the TensorFlow backend downloads weights from
  [JonathanCMitchell/mobilenet_v2_keras](https://github.com/JonathanCMitchell/mobilenet_v2_keras).
  The free runtime includes a converted float16 LiteRT copy and provenance manifest.
  The upstream MIT notice is included in
  [MOBILENET_LICENSE.txt](../src/foodlogger/data/MOBILENET_LICENSE.txt).
- LiteRT: [Google AI Edge LiteRT](https://github.com/google-ai-edge/LiteRT),
  Apache 2.0. Used for lightweight CPU inference.
- ImageNet: [image-net.org](https://www.image-net.org/). Class IDs follow ImageNet
  ordering; ImageNet training data is not included.
- Food-101: Bossard, Guillaumin and Van Gool, *Food-101 – Mining Discriminative
  Components with Random Forests*, ECCV 2014.
  [Dataset and terms](https://data.vision.ee.ethz.ch/cvl/datasets_extra/food-101/).
  The conversion helper operates on a separately obtained dataset; no dataset
  photos or trained Food-101 weights are distributed here.
- Nutrition reference: [USDA FoodData Central](https://fdc.nal.usda.gov/). The
  bundled values are illustrative estimates, not an attributed record-level
  export or an endorsement by USDA.
- Development-only pizza smoke-test photo:
  [mrdbourke/tensorflow-deep-learning](https://github.com/mrdbourke/tensorflow-deep-learning/blob/main/images/03-pizza-dad.jpeg).
  It is not included in the repository or application assets.

- Open Food Facts: [database](https://world.openfoodfacts.org/),
  [API documentation](https://openfoodfacts.github.io/openfoodfacts-server/api/),
  [terms and database licence](https://world.openfoodfacts.org/terms-of-use).
  Product information is contributed by the community under the Open Database
  License (ODbL); individual database contents use the Database Contents License.
  The UI attributes retrieved records and links to their source. Product images
  are not downloaded. Saved product snapshots retain available original nutrient
  data; coverage and accuracy depend on the upstream record. Derived databases
  and redistribution must follow the upstream attribution/share-alike terms.
- ZXing-C++: [source](https://github.com/zxing-cpp/zxing-cpp), Apache 2.0.
  Used for server-side barcode photo decoding.

- Fredoka: [Google Fonts](https://fonts.google.com/specimen/Fredoka), SIL Open Font License 1.1.
  Latin and Hebrew subsets are served from `src/foodlogger/static/`; the license is in
  [Fredoka-OFL.txt](../src/foodlogger/static/Fredoka-OFL.txt).

The interface uses Fredoka, inline SVG and CSS shapes. No stock
food photos are required by the application. The MIT license applies to this
repository's original code, not third-party models, data or libraries.


## Supabase database certificates

`data/supabase-ca.crt` bundles only the production roots from the official
[Supabase CLI](https://github.com/supabase/cli), pinned to commit
`08c7e7d7f061b39ae9c513d603ac1bfffe79cc9f`. The upstream
[MIT notice](../src/foodlogger/data/SUPABASE_LICENSE.txt) is included.

- [prod-ca-2021.crt](https://github.com/supabase/cli/blob/08c7e7d7f061b39ae9c513d603ac1bfffe79cc9f/apps/cli-go/internal/gen/types/templates/prod-ca-2021.crt):
  expires 26 April 2031; SHA-256 of DER
  `807025ad50d4ed219d2c9c7d299c004f824eb00cf7f65afef607d07b72e6cafa`.
- [prod-ca-2025.crt](https://github.com/supabase/cli/blob/08c7e7d7f061b39ae9c513d603ac1bfffe79cc9f/apps/cli-go/internal/gen/types/templates/prod-ca-2025.crt):
  expires 1 September 2035; SHA-256 of DER
  `5f9b77951a7aa1303f9b58eea9bfa89e358cfdc15f9786ff10d4930a722c9ae2`.

These are public trust certificates, not client credentials or private keys.
They are selected only for Supabase shared pooler database hosts; other services'
trust stores are unaffected. The application does not fetch new roots at startup.
For rotation, obtain replacements from Supabase's official distribution, verify
their provenance and fingerprints, update the tests, and redeploy. Staging roots
are not included. See [Supabase's TLS guidance](https://supabase.com/docs/guides/platform/ssl-enforcement).
